from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.utils.time import now


class BucketGateDataset(Base):
    """门岗区间车数批次（每个市场日各等候区间的车辆数）。"""

    __tablename__ = 'bucket_gate_datasets'
    __table_args__ = (UniqueConstraint('name', 'checksum'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    filename: Mapped[str] = mapped_column(String(160))
    checksum: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON)
    row_count: Mapped[int]
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)


class BucketLedgerDataset(Base):
    """周总等待分钟批次（逐市场逐自然周）。

    同一业务名称的周账可多次导入；每次导入都是不可变新版本，版本号自增。
    上游周总数更新即指向新版本，并触发引用旧版本的上下限运行重算。
    """

    __tablename__ = 'bucket_ledger_datasets'
    __table_args__ = (UniqueConstraint('name', 'version'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    filename: Mapped[str] = mapped_column(String(160))
    checksum: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON)
    row_count: Mapped[int]
    version: Mapped[int]
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)


class BoundRun(Base):
    """区间车数 + 周账约束下的双重差分上下限运行。"""

    __tablename__ = 'bound_runs'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    gate_dataset_id: Mapped[int] = mapped_column(ForeignKey('bucket_gate_datasets.id'))
    ledger_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('bucket_ledger_datasets.id'))
    status: Mapped[str] = mapped_column(String(20), index=True, default='queued')
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(500))
    export_file: Mapped[str | None] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None]

    # 失效与替换血缘：上游周账更新后，引用旧周账版本的运行先标记失效，
    # 重算成功后才写入 superseded_by 并把状态置为 superseded。
    stale: Mapped[bool] = mapped_column(default=False, index=True)
    stale_reason: Mapped[str | None] = mapped_column(String(300))
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey('bound_runs.id'))
    replaces_run_id: Mapped[int | None] = mapped_column(ForeignKey('bound_runs.id'))
    ledger_version: Mapped[int | None]

    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]
