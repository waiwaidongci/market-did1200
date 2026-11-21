from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.config.settings import ARTIFACTS
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.domain.spec import SPEC
from src.models.bucket import BoundRun, BucketGateDataset, BucketLedgerDataset
from src.models.identity import User
from src.schemas.requests import BoundRunRequest, BucketUpload
from src.services import bound_runs
from src.services.audit import record
from src.services.bucket_data import (gate_template, ledger_template, parse_gate_csv,
                                      parse_ledger_csv, save_gate, save_ledger)
from src.utils import bucket_views
from src.utils.wakeup import wake

router = APIRouter(prefix='/bucket')
_BUCKET = SPEC['bucket']


@router.get('/spec')
def bucket_spec(actor: User = Depends(current)):
    return {'buckets': _BUCKET['buckets'],
            'gate_fields': _BUCKET['bucket_fields'],
            'count_field': _BUCKET['count_field'],
            'ledger_fields': _BUCKET['ledger_fields'],
            'params': SPEC['params'],
            'methodology': _BUCKET['methodology'],
            'title': _BUCKET['title']}


@router.get('/template/gate')
def gate_sample(actor: User = Depends(current)):
    filename = quote(_BUCKET['sample_gate'])
    return Response(gate_template(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"})


@router.get('/template/ledger')
def ledger_sample(actor: User = Depends(current)):
    filename = quote(_BUCKET['sample_ledger'])
    return Response(ledger_template(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"})


@router.get('/gate-datasets')
def gate_datasets(db: Session = Depends(connection), actor: User = Depends(current)):
    items = db.scalars(select(BucketGateDataset).order_by(BucketGateDataset.id.desc()).limit(100))
    return [bucket_views.gate_dataset(item) for item in items]


@router.get('/ledger-datasets')
def ledger_datasets(db: Session = Depends(connection), actor: User = Depends(current)):
    items = db.scalars(select(BucketLedgerDataset).order_by(
        BucketLedgerDataset.name, BucketLedgerDataset.version.desc()).limit(100))
    return [bucket_views.ledger_dataset(item) for item in items]


@router.get('/gate-datasets/{dataset_id}')
def gate_detail(dataset_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(BucketGateDataset, dataset_id)
    if not item:
        raise HTTPException(404, '找不到该门岗批次')
    return {**bucket_views.gate_dataset(item), 'rows': item.rows}


@router.post('/gate-datasets', status_code=201)
def upload_gate(body: BucketUpload, db: Session = Depends(connection),
                actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    rows = parse_gate_csv(body.csv_text)
    item, created = save_gate(db, body.name, body.filename, rows, actor.username)
    if created:
        record(db, actor.username, 'bucket_gate.imported', item.id, rows=item.row_count)
    db.commit()
    return {**bucket_views.gate_dataset(item), 'created': created}


@router.post('/ledger-datasets', status_code=201)
def upload_ledger(body: BucketUpload, db: Session = Depends(connection),
                  actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    rows = parse_ledger_csv(body.csv_text)
    item, created = save_ledger(db, body.name, body.filename, rows, actor.username)
    recompute = []
    if created:
        record(db, actor.username, 'bucket_ledger.imported', item.id,
               rows=item.row_count, version=item.version)
        # 上游周总数更新：标记引用旧版本的运行失效，并登记重算。
        stale_ids = bound_runs.mark_stale_for_ledger(db, item, actor.username)
        if stale_ids:
            recompute = bound_runs.recompute_stale(db, actor.username)
    db.commit()
    wake()
    return {**bucket_views.ledger_dataset(item), 'created': created,
            'stale_run_ids': [old for old, _new in recompute],
            'replacement_run_ids': [new for _old, new in recompute]}


@router.get('/runs')
def run_index(db: Session = Depends(connection), actor: User = Depends(current)):
    items = db.scalars(select(BoundRun).order_by(BoundRun.id.desc()).limit(100))
    return [bucket_views.bound_run(item) for item in items]


@router.post('/runs', status_code=202)
def run_create(body: BoundRunRequest, db: Session = Depends(connection),
               actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    item = bound_runs.enqueue(db, body.name, body.gate_dataset_id, body.ledger_dataset_id,
                              body.params, actor.username)
    db.commit()
    wake()
    return bucket_views.bound_run(item, detail=True)


@router.get('/runs/{run_id}')
def run_detail(run_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(BoundRun, run_id)
    if not item:
        raise HTTPException(404, '找不到该上下限运行')
    return bucket_views.bound_run(item, detail=True)


@router.get('/runs/{run_id}/export')
def run_export(run_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(BoundRun, run_id)
    if not item:
        raise HTTPException(404, '找不到该上下限运行')
    if not item.export_file:
        raise HTTPException(409, '此记录尚无可下载结果')
    path = ARTIFACTS / item.export_file
    if not path.is_file():
        raise HTTPException(410, '导出文件已不可用，请重新运行')
    return FileResponse(path, media_type='text/csv',
                        filename=f'{_BUCKET["short_name"]}-{item.id}.csv')


@router.post('/runs/{run_id}/recompute', status_code=202)
def run_recompute(run_id: int, db: Session = Depends(connection),
                  actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    old = db.get(BoundRun, run_id)
    if not old:
        raise HTTPException(404, '找不到该上下限运行')
    if not old.stale or old.superseded_by is not None:
        raise HTTPException(409, '只有已失效且尚未替换的运行可以发起重算')
    if old.replaces_run_id is not None:
        raise HTTPException(409, '重算运行不能再次重算')
    created = bound_runs.recompute_stale(db, actor.username)
    match = [new for old_id, new in created if old_id == run_id]
    if not match:
        raise HTTPException(409, '当前没有可登记的重算任务')
    db.commit()
    wake()
    new_run = db.get(BoundRun, match[0])
    return bucket_views.bound_run(new_run, detail=True)
