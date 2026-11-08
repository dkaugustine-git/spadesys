"""API response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    pipeline: str
    status: str
    original_filename: str | None
    stats: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    table_name: str
    row_count: int
    created_at: datetime
    updated_at: datetime
    last_run: RunOut | None = None


class SourceDetail(SourceOut):
    inferred_schema: dict[str, Any] | None
    runs: list[RunOut]


class Preview(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    stage: str
    message: str
    source_id: uuid.UUID | None
    run_id: uuid.UUID | None
    source_name: str | None
    detail: dict[str, Any] | None


class GenerateRequest(BaseModel):
    customers: int = 200
    items: int = 50
    orders: int = 1_000
    seed: int | None = None


class Suggestion(BaseModel):
    source_id: uuid.UUID
    source_name: str
    table_name: str
    row_count: int
    score: int
    reasons: list[str]
    recommended: bool


class FileAnalysis(BaseModel):
    key: str
    filename: str
    size: int
    row_count: int
    columns: list[str]
    preview_rows: list[list[Any]]
    suggestions: list[Suggestion]
    suggested_new_name: str
    suggested_table_name: str
