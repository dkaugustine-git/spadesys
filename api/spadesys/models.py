import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import get_settings
from .db import Base

SCHEMA = get_settings().meta_schema


class Source(Base):
    """A dataset Spadesys knows about. Today: an uploaded CSV landing in raw.<table_name>."""

    __tablename__ = "sources"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="csv")
    table_name: Mapped[str] = mapped_column(String(63), unique=True)
    inferred_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list["Run"]] = relationship(
        back_populates="source", order_by="Run.created_at.desc()", cascade="all, delete-orphan"
    )


class Run(Base):
    """One execution of an ingestion pipeline. Doubles as the job queue row (status='queued')."""

    __tablename__ = "runs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.sources.id", ondelete="CASCADE"))
    pipeline: Mapped[str] = mapped_column(String(64), default="csv_ingest")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    object_key: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)  # set when a pipeline queued it

    source: Mapped[Source] = relationship(back_populates="runs")


class Pipeline(Base):
    """Moves data from a source to a destination, on demand or by watching.

    Today: source = a folder under data/inbox (files dropped there, or added through the UI),
    destination = a Spadesys table. Each file found becomes one Run; afterwards the file is
    archived (kept in storage under archive/, and moved to the folder's _done subfolder).
    """

    __tablename__ = "pipelines"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    source_kind: Mapped[str] = mapped_column(String(32), default="folder")
    source_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # {"folder": "orders", "pattern": "*.csv"}
    destination_kind: Mapped[str] = mapped_column(String(32), default="spadesys")
    destination_source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(16), default="manual")  # manual | watch
    watch_seconds: Mapped[int] = mapped_column(Integer, default=10)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    """A human-readable log line: one step of what the system did, written as it happens.

    No foreign keys on purpose: events are written in their own transaction the
    moment something happens, sometimes before the source/run row is committed.
    """

    __tablename__ = "events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stage: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_name: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Connection(Base):
    """A database server Spadesys can browse (e.g. a developer's dev database).

    Password is stored as-is in Spadesys's own database: use dev credentials.
    """

    __tablename__ = "connections"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))  # postgresql | mysql
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    database: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    password: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
