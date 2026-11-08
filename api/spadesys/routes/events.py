from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Event
from ..schemas import EventOut

router = APIRouter(prefix="/events", tags=["activity"])
DB = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[EventOut])
def list_events(session: DB, after_id: int = 0, source_id: uuid.UUID | None = None, limit: int = 300):
    """Activity log, oldest first. Poll with after_id=<last id you saw> to get only new lines."""
    q = select(Event).where(Event.id > after_id)
    if source_id:
        q = q.where(Event.source_id == source_id)
    if after_id:
        q = q.order_by(Event.id).limit(max(1, min(limit, 1000)))
        return session.scalars(q).all()
    # First load: the most recent `limit` lines, returned oldest first.
    rows = session.scalars(q.order_by(Event.id.desc()).limit(max(1, min(limit, 1000)))).all()
    return list(reversed(rows))
