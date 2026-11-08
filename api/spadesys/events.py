"""Activity log: record each step in plain English, committed immediately so the UI sees it live."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert

from .db import engine
from .models import Event

log = logging.getLogger("spadesys.events")


def emit(
    stage: str,
    message: str,
    *,
    source_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    source_name: str | None = None,
    **detail: Any,
) -> None:
    log.info("[%s] %s%s", stage, f"{source_name}: " if source_name else "", message)
    try:
        with engine.begin() as conn:
            conn.execute(
                insert(Event).values(
                    ts=datetime.now(timezone.utc),
                    stage=stage,
                    message=message,
                    source_id=source_id,
                    run_id=run_id,
                    source_name=source_name,
                    detail=detail or None,
                )
            )
    except Exception:  # noqa: BLE001  (logging must never break a pipeline)
        log.exception("failed to record event")


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"
