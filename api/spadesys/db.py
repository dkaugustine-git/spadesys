from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create schemas and metadata tables. Swap for Alembic once the model settles."""
    from . import models  # noqa: F401  (register tables)

    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.meta_schema}"'))
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.raw_schema}"'))
    Base.metadata.create_all(engine)
    # Small additions to existing tables (no Alembic yet).
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{settings.meta_schema}".runs ADD COLUMN IF NOT EXISTS pipeline_id uuid'))
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS ix_runs_pipeline_id ON "{settings.meta_schema}".runs (pipeline_id)'))


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
