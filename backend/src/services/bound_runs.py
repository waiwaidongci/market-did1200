"""上下限运行的入队、上游失效标记与重算血缘。"""

import logging
from datetime import timedelta
from sqlalchemy import or_, select
from src.config.database import Session
from src.constants.enums import Status
from src.domain.bucket_bounds import analyze_bounds
from src.models.bucket import BoundRun, BucketGateDataset, BucketLedgerDataset
from src.services.audit import record
from src.services.validation import normalize_params
from src.utils.time import now
from src.utils.exports import write_bound_report

log = logging.getLogger(__name__)


def enqueue(db, name, gate_dataset_id, ledger_dataset_id, params, actor):
    gate = db.get(BucketGateDataset, gate_dataset_id)
    if not gate:
        raise ValueError('找不到指定的门岗区间车数批次')
    ledger = db.get(BucketLedgerDataset, ledger_dataset_id) if ledger_dataset_id else None
    if ledger_dataset_id and not ledger:
        raise ValueError('找不到指定的周账批次')
    run = BoundRun(
        name=name, gate_dataset_id=gate_dataset_id,
        ledger_dataset_id=ledger_dataset_id if ledger else None,
        ledger_version=ledger.version if ledger else None,
        params=normalize_params(params), status=Status.QUEUED, author=actor,
    )
    db.add(run)
    db.flush()
    record(db, actor, 'bound_run.queued', run.id,
           gate_dataset_id=gate_dataset_id, ledger_dataset_id=ledger_dataset_id)
    return run


def mark_stale_for_ledger(db, new_ledger, actor='system'):
    """周账新版本入库后，把引用同名旧版本、且尚未失效的运行标记失效。

    既覆盖原始运行，也覆盖仍在途、引用旧版本的重算运行；后者即使之后完成，
    也不允许替换旧结果（见 execute_bound 的 stale 复核）。返回受影响运行 id。
    """
    old_versions = db.scalars(select(BucketLedgerDataset).where(
        BucketLedgerDataset.name == new_ledger.name,
        BucketLedgerDataset.id != new_ledger.id)).all()
    old_ids = [item.id for item in old_versions]
    if not old_ids:
        return []
    affected = db.scalars(select(BoundRun).where(
        BoundRun.ledger_dataset_id.in_(old_ids),
        BoundRun.stale.is_(False))).all()
    run_ids = []
    reason = (f'上游周账「{new_ledger.name}」更新至第 {new_ledger.version} 版，'
              '旧结果标记失效，等待按最新版本重算替换。')
    for run in affected:
        run.stale = True
        run.stale_reason = reason
        # 保留原 status，仅用 stale 表达失效；领取与替换环节会过滤 stale 运行。
        record(db, actor, 'bound_run.stale', run.id,
               ledger_dataset_id=new_ledger.id, ledger_version=new_ledger.version)
        run_ids.append(run.id)
    return run_ids


def recompute_stale(db, actor='system'):
    """为失效的原始运行创建指向同名周账最新版本的重算运行。

    旧结果保持失效，直到重算成功才写入 superseded_by 并置为 superseded。
    若某原始运行已有未失效（新鲜）的在途重算，则不重复创建；已失效的在途
    重算会被新的最新版重算取代，且因其 stale=True 不会完成替换。
    """
    # 新鲜在途重算：replaces_run_id 非空且自身未失效，按其替换的根运行去重。
    active_for_root = {}
    for run in db.scalars(select(BoundRun).where(BoundRun.replaces_run_id.is_not(None))).all():
        if run.replaces_run_id is not None and not run.stale:
            active_for_root.setdefault(run.replaces_run_id, run.id)

    stale_roots = db.scalars(select(BoundRun).where(
        BoundRun.stale.is_(True), BoundRun.superseded_by.is_(None),
        BoundRun.replaces_run_id.is_(None))).all()
    created = []
    for old in stale_roots:
        if old.id in active_for_root:
            continue
        ledger = db.get(BucketLedgerDataset, old.ledger_dataset_id)
        if ledger is None:
            continue
        latest = db.scalar(select(BucketLedgerDataset).where(
            BucketLedgerDataset.name == ledger.name
        ).order_by(BucketLedgerDataset.version.desc()))
        if not latest:
            continue
        replacement = BoundRun(
            name=f'{old.name}（周账 v{latest.version} 重算）',
            gate_dataset_id=old.gate_dataset_id, ledger_dataset_id=latest.id,
            ledger_version=latest.version, params=dict(old.params),
            status=Status.QUEUED, author=actor, replaces_run_id=old.id,
        )
        db.add(replacement)
        db.flush()
        record(db, actor, 'bound_run.recompute_queued', replacement.id,
               replaces_run_id=old.id, ledger_version=latest.version)
        created.append((old.id, replacement.id))
    return created


def claim_bound():
    stamp = now()
    with Session.begin() as db:
        query = select(BoundRun).where(
            BoundRun.stale.is_(False),
            or_(
                BoundRun.status == Status.QUEUED,
                (BoundRun.status == Status.RUNNING) & (BoundRun.lease_until < stamp)))
        job = db.scalar(query.order_by(BoundRun.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        if job.attempt >= 3:
            job.status = Status.FAILED
            job.error = '后台进程多次中断，请发起新的运行'
            job.finished_at = stamp
            record(db, 'worker', 'bound_run.failed', job.id, reason=job.error)
            return None
        job.status = Status.RUNNING
        job.attempt += 1
        job.lease_until = stamp + timedelta(minutes=3)
        gate = db.get(BucketGateDataset, job.gate_dataset_id)
        ledger = db.get(BucketLedgerDataset, job.ledger_dataset_id) if job.ledger_dataset_id else None
        return (job.id, job.attempt, list(gate.rows),
                list(ledger.rows) if ledger else [], dict(job.params),
                job.replaces_run_id)


def execute_bound(lease):
    job_id, attempt, gate_rows, ledger_rows, params, replaces_id = lease
    result = export = failure = None
    try:
        result = analyze_bounds(gate_rows, ledger_rows, params)
        export = write_bound_report(job_id, attempt, result)
    except ValueError as error:
        failure = str(error)[:500]
    except Exception:
        log.exception('Bound run %s failed', job_id)
        failure = '计算失败，请检查区间与周账口径后重试'
    with Session.begin() as db:
        job = db.get(BoundRun, job_id, with_for_update=True)
        if job.attempt != attempt or job.status != Status.RUNNING:
            return
        job.lease_until = None
        job.finished_at = now()
        # 计算期间上游周账再次更新：无论计算成败，本重算引用的周账已过时，
        # 作废且不替换旧结果，由更新版重算接管。
        if job.stale:
            job.status = Status.FAILED
            job.error = failure or '计算期间上游周账已更新，本重算结果作废，请以最新版重算为准。'
            record(db, 'worker', 'bound_run.obsolete', job.id, attempt=attempt, reason=failure)
            return
        if failure:
            job.status = Status.FAILED
            job.error = failure
            record(db, 'worker', 'bound_run.failed', job.id, attempt=attempt, reason=failure)
            return
        job.status = Status.COMPLETE
        job.result = result
        job.export_file = export
        job.error = None
        record(db, 'worker', 'bound_run.complete', job.id, attempt=attempt)
        # 重算成功后才替换旧结果。
        if replaces_id:
            old = db.get(BoundRun, replaces_id, with_for_update=True)
            if old and old.stale and old.superseded_by is None:
                old.superseded_by = job.id
                old.status = Status.SUPERSEDED
                record(db, 'worker', 'bound_run.superseded', old.id, superseded_by=job.id)
