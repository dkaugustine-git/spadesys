from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import __version__, cloudbeaver, storage
from .db import SessionLocal, get_session, init_db
from .generators.commerce import generate, to_csv_bytes
from .events import emit
from .routes import databases, devdata, events, pipelines, runs, sources, storage_browser, uploads
from .schemas import GenerateRequest, SourceOut
from .services import ingest_csv


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    storage.ensure_bucket()
    with SessionLocal() as session:
        cloudbeaver.sync(session)
    yield


app = FastAPI(title="Spadesys", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
api = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_session)]


@api.get("/health", tags=["system"])
def health(session: DB):
    checks: dict[str, str] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["postgres"] = f"error: {e}"
    try:
        storage.ensure_bucket()
        checks["object_storage"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["object_storage"] = f"error: {e}"
    return {"status": "ok" if all(v == "ok" for v in checks.values()) else "degraded", "version": __version__, "checks": checks}


@api.post("/generate/commerce", response_model=list[SourceOut], status_code=201, tags=["generators"])
def generate_commerce(session: DB, req: GenerateRequest):
    """Generate Faker commerce data and ingest each table as a new source."""
    emit("generate", "You clicked “Generate sample commerce data”. Making fake data with the Faker library…")
    tables = generate(req.customers, req.items, req.orders, req.seed)
    emit(
        "generate",
        "Made 4 linked CSV files: " + ", ".join(f"{name} ({len(rows):,} rows)" for name, rows in tables.items()),
    )
    created = []
    for name, rows in tables.items():
        source = ingest_csv(session, f"{name}.csv", to_csv_bytes(rows), name=f"Sample · {name}", folder="samples")
        created.append(SourceOut.model_validate(source))
    return created


api.include_router(sources.router)
api.include_router(runs.router)
api.include_router(events.router)
api.include_router(uploads.router)
api.include_router(storage_browser.router)
api.include_router(devdata.router)
api.include_router(databases.router)
api.include_router(pipelines.router)
app.include_router(api)
