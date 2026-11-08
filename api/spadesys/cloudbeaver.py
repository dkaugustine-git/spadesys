"""Keep CloudBeaver's list of databases in step with Spadesys.

CloudBeaver reads extra connection files from its workspace at startup. We write one file,
data-sources-spadesys.json; tools/cloudbeaver/start.sh restarts CloudBeaver when it changes.
Only rewritten when the list actually changes, so CloudBeaver isn't restarted for nothing.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .events import emit
from .models import Connection

WORKSPACE = Path(os.environ.get("CLOUDBEAVER_WORKSPACE", "/cloudbeaver"))
LIST_FILE = WORKSPACE / "GlobalConfiguration" / ".dbeaver" / "data-sources-spadesys.json"
INTERNAL_URL = "http://cloudbeaver:8978/cloudbeaver/"

DRIVERS = {"postgresql": ("postgresql", "postgres-jdbc"), "mysql": ("mysql", "mysql8")}


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _entry(name: str, kind: str, host: str, port: int, database: str, user: str, password: str, folder: str) -> dict[str, Any]:
    provider, driver = DRIVERS[kind]
    scheme = "postgresql" if kind == "postgresql" else "mysql"
    cfg: dict[str, Any] = {
        "host": host,
        "port": str(port),
        "database": database,
        "url": f"jdbc:{scheme}://{host}:{port}/{database}",
        "configurationType": "MANUAL",
        "type": "dev",
        "auth-model": "native",
        "user": user,
        "password": password,
    }
    if kind == "mysql":
        cfg["properties"] = {"allowPublicKeyRetrieval": "true", "useSSL": "false"}
    return {"provider": provider, "driver": driver, "name": name, "folder": folder, "save-password": True, "configuration": cfg}


def wanted(session: Session) -> dict[str, dict[str, Any]]:
    """Every database Spadesys knows about and can reach right now."""
    env = os.environ.get
    out = {
        "spadesys-postgres": _entry(
            "Spadesys (Postgres)", "postgresql", "postgres", 5432, env("POSTGRES_DB", "spadesys"),
            env("POSTGRES_USER", "spadesys"), env("POSTGRES_PASSWORD", "spadesys"), "Spadesys",
        )
    }
    if _reachable("mysql", 3306):
        out["spadesys-mysql"] = _entry("Sample source (MySQL)", "mysql", "mysql", 3306, "source_app", "root",
                                       env("MYSQL_ROOT_PASSWORD", "spadesys"), "Spadesys")
    if _reachable("doris-fe", 9030):
        out["spadesys-doris"] = _entry("Warehouse (Doris)", "mysql", "doris-fe", 9030, "", "root", "", "Spadesys")
    for c in session.scalars(select(Connection).order_by(Connection.name)):
        out[f"spadesys-{c.id}"] = _entry(c.name, c.kind, c.host, c.port, c.database, c.username, c.password, "Your connections")
    return out


def sync(session: Session) -> dict[str, Any]:
    connections = wanted(session)
    doc = {"folders": {"Spadesys": {}, "Your connections": {}}, "connections": connections}
    text = json.dumps(doc, indent=2, sort_keys=True)
    names = [c["name"] for c in connections.values()]
    try:
        current = LIST_FILE.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current == text:
        return {"changed": False, "connections": names}
    try:
        LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LIST_FILE.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(LIST_FILE)
    except OSError as exc:
        return {"changed": False, "connections": names, "error": f"Couldn't write CloudBeaver's list: {exc}"}
    emit("connect", f"Updated CloudBeaver's database list ({', '.join(names)}). CloudBeaver restarts to pick it up, about 20 seconds.")
    return {"changed": True, "connections": names}


def is_up() -> bool:
    try:
        with urllib.request.urlopen(INTERNAL_URL, timeout=1) as r:
            return r.status == 200
    except OSError:
        return False
