import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from scripts.seed_demo import seed
from src.config.database import Base, engine
from src.config.settings import SEED_DEMO
from src.domain.spec import SPEC
from src.middlewares import errors, headers, rate
# 显式导入全部模型，确保 Base.metadata.create_all 建出区间/周账相关表。
from src.models import bucket as _bucket_models  # noqa: F401
from src.models import identity as _identity_models  # noqa: F401
from src.models import jobs as _jobs_models  # noqa: F401
from src.models import source as _source_models  # noqa: F401
from src.routes import bucket, distribution, identity, registry, runs
from src.utils.wakeup import broker

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app):
    Base.metadata.create_all(engine)
    if SEED_DEMO:
        try:
            log.info('Seeded %s', seed())
        except Exception:
            log.exception('Demo seed failed')
    yield
    engine.dispose()


app = FastAPI(title=SPEC['title'], lifespan=lifespan)
errors.install(app)
headers.install(app)
rate.install(app)
for module in (identity, registry, runs, bucket):
    app.include_router(module.router)
if SPEC.get('scheduled'):
    app.include_router(distribution.router)


@app.get('/healthz', include_in_schema=False)
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    broker.ping()
    return {'status': 'ok'}
