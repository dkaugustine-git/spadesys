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
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.clean_schema}"'))
    Base.metadata.create_all(engine)
    # Small additions to existing tables (no Alembic yet).
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{settings.meta_schema}".runs ADD COLUMN IF NOT EXISTS pipeline_id uuid'))
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS ix_runs_pipeline_id ON "{settings.meta_schema}".runs (pipeline_id)'))
        conn.execute(text(f'ALTER TABLE "{settings.meta_schema}".runs ADD COLUMN IF NOT EXISTS extract_id uuid'))
        conn.execute(text(f'ALTER TABLE "{settings.meta_schema}".runs ADD COLUMN IF NOT EXISTS layout jsonb'))
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS ix_runs_extract_id ON "{settings.meta_schema}".runs (extract_id)'))
        conn.execute(text(f'ALTER TABLE "{settings.meta_schema}".pipelines ADD COLUMN IF NOT EXISTS extract_id uuid'))
        for col in ("source_kind", "source_config", "destination_kind"):
            conn.execute(text(f'ALTER TABLE "{settings.meta_schema}".pipelines ALTER COLUMN {col} DROP NOT NULL'))
    _move_pipelines_to_extracts()


def _move_pipelines_to_extracts() -> None:
    """Pipelines made before extracts existed carried their own source. Give each one an extract."""
    from sqlalchemy import select

    from .models import Extract, Pipeline, Run

    with SessionLocal() as session:
        for p in session.scalars(select(Pipeline).where(Pipeline.extract_id.is_(None))):
            if not p.source_config:
                continue
            ex = Extract(name=p.name, kind=p.source_kind or "folder", config=dict(p.source_config),
                         source_id=p.destination_source_id)
            session.add(ex)
            session.flush()
            p.extract_id = ex.id
            session.execute(
                Run.__table__.update().where(Run.pipeline_id == p.id).values(extract_id=ex.id)
            )
        session.commit()


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
