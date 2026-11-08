"""The Databases tab: CloudBeaver (web DBeaver) with every database Spadesys knows about."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import cloudbeaver
from ..db import get_session

router = APIRouter(prefix="/databases", tags=["databases"])
DB = Annotated[Session, Depends(get_session)]


@router.get("/cloudbeaver")
def status(session: DB):
    return {"up": cloudbeaver.is_up(), "connections": [c["name"] for c in cloudbeaver.wanted(session).values()]}


@router.post("/cloudbeaver/sync")
def sync(session: DB):
    return cloudbeaver.sync(session)
