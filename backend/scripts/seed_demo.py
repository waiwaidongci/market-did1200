import json
from sqlalchemy import func, select
from src.config.database import Session
from src.constants.enums import Role
from src.domain.bucket_demo import demo_gate_rows, demo_ledger_rows
from src.domain.demo import demo_rows
from src.domain.spec import SPEC
from src.models.bucket import BucketGateDataset, BucketLedgerDataset
from src.models.identity import User
from src.models.source import Dataset
from src.services.bucket_data import save_gate, save_ledger
from src.services.datasets import save
from src.utils.security import hash_password


def seed():
    with Session.begin() as db:
        for role in Role:
            if not db.get(User, role.value):
                db.add(User(username=role.value, role=role, password_hash=hash_password(f'{role.value}-demo-2611')))
        item, created = save(db, SPEC['default_dataset'], SPEC['sample_name'], demo_rows(), 'seed')
        gate, gate_created = save_gate(
            db, SPEC['bucket']['default_gate'], SPEC['bucket']['sample_gate'], demo_gate_rows(), 'seed')
        ledger, ledger_created = save_ledger(
            db, SPEC['bucket']['default_ledger'], SPEC['bucket']['sample_ledger'],
            demo_ledger_rows(), 'seed')
        return {'users': db.scalar(select(func.count()).select_from(User)),
                'datasets': db.scalar(select(func.count()).select_from(Dataset)),
                'seed_dataset_id': item.id, 'row_count': item.row_count, 'checksum': item.checksum,
                'created_dataset': created,
                'gate_dataset_id': gate.id, 'gate_rows': gate.row_count, 'gate_created': gate_created,
                'ledger_dataset_id': ledger.id, 'ledger_version': ledger.version,
                'ledger_rows': ledger.row_count, 'ledger_created': ledger_created}


if __name__ == '__main__':
    print(json.dumps(seed(), ensure_ascii=False))
