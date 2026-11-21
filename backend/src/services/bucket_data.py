"""门岗区间车数与周总等待分钟批次的解析、指纹与存储。"""

import csv
import hashlib
import io
import json
from datetime import date
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from src.domain.bucket_bounds import validate_gate_rows, validate_ledger_rows
from src.domain.spec import SPEC
from src.models.bucket import BucketGateDataset, BucketLedgerDataset
from src.services.validation import cell

_BUCKET = SPEC['bucket']
_GATE_FIELDS = _BUCKET['bucket_fields']
_COUNT = _BUCKET['count_field']
_LEDGER_FIELDS = _BUCKET['ledger_fields']
_BUCKET_KEYS = tuple(item['key'] for item in _BUCKET['buckets'])


def _checksum(rows):
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _read_csv(text):
    reader = csv.DictReader(io.StringIO(text.removeprefix('﻿'), newline=''), strict=True)
    headers = reader.fieldnames or []
    return reader, headers


def parse_gate_csv(text):
    """门岗 CSV：基础列 + 每个等候区间一列车辆数（区间列必须齐全，缺报填 0）。"""
    reader, headers = _read_csv(text)
    base_keys = [field['key'] for field in _GATE_FIELDS]
    required = set(base_keys) | set(_BUCKET_KEYS)
    if not required <= set(headers) or len(headers) != len(set(headers)):
        raise ValueError('门岗 CSV 表头缺少区间车辆数列或与字段说明不符，请下载模板检查列名')
    raw_rows = []
    try:
        for raw in reader:
            if len(raw_rows) >= 5000:
                raise ValueError('一个门岗批次最多导入 5000 行')
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError('工作表的列数与表头不一致')
            base = {field['key']: cell(field, raw.get(field['key'])) for field in _GATE_FIELDS}
            counts = {}
            for key in _BUCKET_KEYS:
                value = raw.get(key, '0')
                value = '0' if value in (None, '') else value
                counts[key] = cell(_COUNT, value)
            raw_rows.append({**base, 'counts': counts})
    except csv.Error:
        raise ValueError(f'门岗 CSV 第 {reader.line_num} 行附近格式不正确') from None
    return validate_gate_rows(raw_rows)


def parse_ledger_csv(text):
    """周账 CSV：market_id, week_start, total_wait_minutes。"""
    reader, headers = _read_csv(text)
    keys = [field['key'] for field in _LEDGER_FIELDS]
    required = set(keys)
    if not required <= set(headers) or not set(headers) <= required or len(headers) != len(set(headers)):
        raise ValueError('周账 CSV 表头与字段说明不符，请下载模板检查列名')
    raw_rows = []
    try:
        for raw in reader:
            if len(raw_rows) >= 5000:
                raise ValueError('一个周账批次最多导入 5000 行')
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError('工作表的列数与表头不一致')
            raw_rows.append({field['key']: cell(field, raw.get(field['key'])) for field in _LEDGER_FIELDS})
    except csv.Error:
        raise ValueError(f'周账 CSV 第 {reader.line_num} 行附近格式不正确') from None
    # 复用领域校验（分组/周一/重复/取值），通过后规范化为行式存储。
    validate_ledger_rows(raw_rows)
    normalized = []
    for row in raw_rows:
        week = date.fromisoformat(row['week_start'])
        normalized.append({
            'market_id': row['market_id'].strip(),
            'week_start': week.isoformat(),
            'total_wait_minutes': row['total_wait_minutes'],
        })
    return normalized


def save_gate(db, name, filename, rows, actor):
    signature = _checksum(rows)
    lookup = select(BucketGateDataset).where(BucketGateDataset.name == name,
                                             BucketGateDataset.checksum == signature)
    existing = db.scalar(lookup)
    if existing:
        return existing, False
    item = BucketGateDataset(name=name, filename=filename, checksum=signature, rows=rows,
                             row_count=len(rows), author=actor)
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(lookup.with_for_update())
        if existing:
            return existing, False
        raise
    return item, True


def save_ledger(db, name, filename, rows, actor):
    """保存周账新版本：同名业务批次版本号自增，内容相同则复用。"""
    signature = _checksum(rows)
    same = db.scalar(select(BucketLedgerDataset).where(BucketLedgerDataset.name == name,
                                                       BucketLedgerDataset.checksum == signature))
    if same:
        return same, False
    current_version = db.scalar(select(func.coalesce(func.max(BucketLedgerDataset.version), 0))
                                .where(BucketLedgerDataset.name == name))
    item = BucketLedgerDataset(name=name, filename=filename, checksum=signature, rows=rows,
                               row_count=len(rows), version=current_version + 1, author=actor)
    db.add(item)
    db.flush()
    return item, True


def gate_template():
    buffer = io.StringIO(newline='')
    header = [field['key'] for field in _GATE_FIELDS] + list(_BUCKET_KEYS)
    writer = csv.DictWriter(buffer, fieldnames=header, extrasaction='ignore')
    writer.writeheader()
    for row in _demo_gate_rows():
        out = {key: row[key] for key in base_key_names()}
        out.update(row['counts'])
        writer.writerow(out)
    return '﻿' + buffer.getvalue()


def ledger_template():
    buffer = io.StringIO(newline='')
    keys = [field['key'] for field in _LEDGER_FIELDS]
    writer = csv.DictWriter(buffer, fieldnames=keys, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(_demo_ledger_rows())
    return '﻿' + buffer.getvalue()


def base_key_names():
    return [field['key'] for field in _GATE_FIELDS]


# --------------------------------------------------------------------------- #
# 演示数据：由均值批次演示数据派生区间车数，并生成与之自洽的周账
# --------------------------------------------------------------------------- #
def _demo_gate_rows():
    from src.domain.bucket_demo import demo_gate_rows
    return demo_gate_rows()


def _demo_ledger_rows():
    from src.domain.bucket_demo import demo_ledger_rows
    return demo_ledger_rows()
