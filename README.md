# ♠ Spadesys

**Simple Pipelines And Data Engineering System**: open-source, containerized data engineering in a box.

Spadesys gives small teams a self-hosted data platform without enterprise consulting retainers or large cloud bills. Run `docker compose up` and you get:

- **Ingestion with a human in the loop:** drop a file, see what's in it, and decide where it goes. Spadesys recommends a table but never creates one behind your back.
- **Pipelines:** watch a folder (on your computer or in storage) and load every file that shows up, then archive it.
- **Dev data:** point at a real table (or paste column headers from a spreadsheet) and generate realistic fake rows that respect types, keys and foreign keys.
- **Storage browser:** folders, upload, download, zip export and delete for everything in object storage.
- **Databases:** CloudBeaver (web DBeaver) built in, already connected to every database Spadesys knows about.
- **API:** every button calls a documented FastAPI endpoint, viewable and callable from the API tab.
- **An Activity log** that explains each step in plain English as it happens.

A warehouse (Apache Doris) and JupyterLab are opt-in profiles.

## Quick start

You don't need to be a developer to run Spadesys. Everything runs inside Docker, so you install Docker once and Spadesys brings everything else with it.

### What you need first

- **Docker Desktop**, free for personal use, education and small businesses. Download it from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) (Windows or Mac). On Linux, install Docker Engine with the Compose plugin.
  - On Windows, the installer may ask to turn on **WSL 2**. Say yes and restart when it asks.
  - Open Docker Desktop once after installing and wait until it says it's running. It needs to be running whenever you use Spadesys.
- **About 4 GB of free memory and 10 GB of disk space.** The optional Doris warehouse needs about 8 GB of memory on its own.
- **The Spadesys files.** Either:
  - **No Git:** on the [GitHub page](https://github.com/dkaugustine-git/spadesys), click the green **Code** button, then **Download ZIP**, and unzip it somewhere you'll find it, such as `Documents\spadesys`.
  - **With Git:** `git clone https://github.com/dkaugustine-git/spadesys.git`

### Start it

1. **Open a terminal in the Spadesys folder.**
   - Windows: open the folder in File Explorer, right-click an empty spot, and choose **Open in Terminal**.
   - Mac: open **Terminal**, type `cd ` (with a space), drag the folder onto the window, and press Enter.
2. **Run this command:**

   ```bash
   docker compose up --build
   ```

   The first start downloads everything Spadesys needs and can take 5 to 15 minutes. Later starts take under a minute. Lots of text will scroll by; that's normal. Leave this window open while you use Spadesys.
3. **Open [http://localhost:5180](http://localhost:5180) in your browser.** If the page doesn't load yet, wait a minute and refresh.

### Stop it and start it again

- **Stop:** click the terminal window and press **Ctrl+C**, or run `docker compose down` from the same folder.
- **Start again:** open a terminal in the folder and run `docker compose up` again.
- Your tables, files and pipelines are kept between restarts. Only `docker compose down -v` erases them.

### Everything it runs

| What | URL |
|---|---|
| Web UI | http://localhost:5180 |
| API docs (also the **API** tab) | http://localhost:8000/api/docs |
| CloudBeaver (also the **Databases** tab) | http://localhost:5180/cloudbeaver/ (admin `cbadmin` / `Spadesys1`) |
| MinIO console | http://localhost:9001 (`spadesys` / `spadesys-secret`) |
| Postgres | `localhost:5432` (`spadesys` / `spadesys`) |

**Port already in use?** Every host port can be changed in `.env` (`POSTGRES_PORT`, `WEB_PORT`, `API_PORT`, `CLOUDBEAVER_PORT`, ...). For example, set `POSTGRES_PORT=5433` if you already run a local Postgres.

## The app

Navigation runs down the left side. It shrinks to icons and becomes a bottom bar on phones.

| Page | What it does |
|---|---|
| **Sources** | Tables you've loaded: columns and inferred types, data preview, load history. Drop a CSV here to stage it; a dialog asks what to do with it and recommends a matching table when the file name or columns match one you've loaded before. When nothing is selected, the live Activity log shows. |
| **Pipelines** | Folder → table, on demand or watching (see below). |
| **Storage** | Browse MinIO like a file explorer: new folder, upload (button or drag and drop), download a file or a whole folder as .zip, delete with confirmation, preview text files, load a CSV into a table, or watch a folder with a pipeline. |
| **Dev data** | Generate fake rows (see below). |
| **Databases** | CloudBeaver inside the app. |
| **API** | FastAPI's interactive docs inside the app. |

## How a file flows through

```
drop / pipeline ──► object storage (MinIO: uploads/…, archive/<pipeline>/…)
                      │   you choose the table (uploads) or the pipeline already knows it
                      ▼   run queued in Postgres (spadesys.runs)
worker ──► validate ──► infer schema ──► hash rows ──► load raw.<table>
```

- **Land first.** The original file is kept in object storage under a readable path (`uploads/2026-11-07/143205_orders.csv`), so every load can be replayed.
- **Validate.** Encoding (UTF-8 / BOM / Latin-1 fallback), delimiter sniffing, empty-file and header checks.
- **Infer.** Each column is typed as boolean, integer, decimal, date, timestamp or text, with null counts, distinct counts and key candidates. Leading-zero values such as zip codes stay text.
- **Hash.** Each row gets a SHA-256 of its normalized raw values. `_row_hash` is the primary key, so loading the same rows again inserts nothing, and new columns are added automatically when the schema drifts.
- **Load.** Typed tables land in the `raw` schema with `_row_hash`, `_run_id` and `_loaded_at` lineage columns.
- **Explain.** Every step writes a plain-English line to the Activity log (`spadesys.events`).

The worker uses Postgres itself as the job queue (`FOR UPDATE SKIP LOCKED`), so there's no Redis or Celery. Scale it with `docker compose up --scale worker=3`.

## Pipelines

A pipeline has a **source**, a **destination table** and a **trigger**.

- **Source: a folder on your computer.** Spadesys makes `data/inbox/<name>/`. Drop files there from Explorer or Finder, or use **Add a file…**. After a file is picked up, a copy goes to storage under `archive/<name>/` and the file moves to `data/inbox/<name>/_done/`. Files still being copied in are left alone until they stop changing.
- **Source: a folder in storage.** Any bucket and prefix in MinIO, so anything that writes S3 can feed it. New objects are moved to `archive/<name>/` and loaded. The Storage tab has a **Watch with a pipeline** button.
- **Destination:** a new or existing Spadesys table.
- **Trigger:** **Run now**, or **watch** (the worker checks every N seconds).
- Only files matching a name pattern (e.g. `orders_*.csv`) are picked up. Nothing is ever deleted, and duplicate rows are skipped by the row hash.

Each pipeline has its own page: where files come from → which table they go to, files waiting and done, loads with row counts, and its own activity feed. Pipeline pages can be bookmarked (`#/pipelines/<id>`).

## Dev data

Make realistic fake rows for a table:

1. **Start from a real table:** save a connection to your own Postgres or MySQL, browse to a table, and Spadesys reads its columns, keys, foreign keys, enums and lengths.
2. **Or paste column headers:** copy a header row (plus a few data rows) from Excel, Google Sheets or a web table. The example rows improve the guesses: leading zeros stay text, repeated values become a pick list, `1/5/2024` is a date, and number ranges follow your data.
3. Each column gets a suggested type and generator **with the reason**, for example: IDs that are all digits are suggested as text, because they're labels, not amounts. Change anything you disagree with and watch the live preview.
4. **Download CSV**, **save to storage**, or **insert into the table** in one all-or-nothing transaction. Foreign-key columns use values that already exist in the parent table; auto-increment columns are left to the database.

**Connecting to a database on your own computer:** Spadesys runs inside Docker, so `localhost` means the Spadesys container. Use `host.docker.internal` instead. That includes databases running in other Docker containers with a published port.

## Databases tab (CloudBeaver)

CloudBeaver starts with the stack, skips its setup screen and lists:

- Spadesys's own Postgres
- MySQL and Doris, when those profiles are running
- every connection you save on the Dev data tab

The list lives in `data-sources-spadesys.json` in CloudBeaver's workspace. Spadesys rewrites it when connections change, and [tools/cloudbeaver/start.sh](tools/cloudbeaver/start.sh) restarts CloudBeaver (about 20 s) to pick it up.

## Profiles

```bash
docker compose --profile warehouse up   # Apache Doris 3.0 FE + BE
docker compose --profile sources up     # MySQL 8.4 (sample source system)
docker compose --profile tools up       # JupyterLab :8888 (token: spadesys)
```

**Doris notes:** Doris needs about 8 GB of RAM for Docker, and its BE requires a higher `vm.max_map_count`. On Docker Desktop (WSL2), run this once after each Docker restart:

```powershell
wsl -d docker-desktop sysctl -w vm.max_map_count=2000000
```

Then connect with any MySQL client on `localhost:9030` (user `root`, no password). [warehouse/doris/001_commerce.sql](warehouse/doris/001_commerce.sql) sketches the hybrid model: customer → orders → items nested as `ARRAY<STRUCT>`, with item details in a lookup table.

## Repo layout

```
api/                   FastAPI control plane + worker (one image, two entrypoints)
  spadesys/
    ingest/            infer.py · hashing.py · load.py · pipeline.py
    devdata/           generators.py · recommend.py · engine.py · dbbrowse.py
    routes/            sources, uploads, runs, events, pipelines, storage_browser, devdata, databases
    pipelines.py       folder / storage watching, archiving
    cloudbeaver.py     keeps CloudBeaver's database list in sync
    events.py          the Activity log
    generators/        Faker commerce data (also a CLI)
    ai/                assistant interface (LLM-assisted schema review: next up)
    worker.py          Postgres-backed job runner + pipeline watcher
  tests/
web/                   React + Vite + TypeScript UI (responsive; PWA/Capacitor-ready)
  src/components/      one file per page plus shared pieces
tools/cloudbeaver/     CloudBeaver start script
warehouse/doris/       Doris DDL
notebooks/             mounted into JupyterLab
data/                  git-ignored; data/inbox/<pipeline> holds pipeline folders
```

## Development

```bash
# API tests (no services needed)
cd api && python -m pip install -e ".[dev]" && python -m pytest
# or inside the stack
docker compose exec api python -m pytest

# Type-check the web app
docker compose exec web npx tsc --noEmit

# Generate sample CSVs to ./data
cd api && python -m spadesys.generators.commerce --out ../data --customers 500 --orders 5000
```

The API, worker and web containers mount your source and hot-reload. The worker restarts only for changes to its own code: `docker compose restart worker`.

## Roadmap

- [x] CSV ingestion, validation, schema inference, row hashing, schema drift
- [x] Ask-first uploads with table recommendations
- [x] Plain-English Activity log
- [x] Storage browser with folders, upload, download, zip export, delete
- [x] Dev data generator: from a live table or pasted headers, with reasons and FK-aware inserts
- [x] Pipelines: folder or storage source → table, on demand or watching, with archiving
- [x] CloudBeaver and API docs built into the UI; sidebar navigation
- [ ] Pipelines with a database table as the source (full or incremental), API sources, Doris as a destination
- [ ] AI assistant: schema review, semantic types / PII, mapping, Doris DDL suggestions, natural-language-to-SQL (pluggable: Claude or local models)
- [ ] Doris loader: raw → nested `ARRAY<STRUCT>` warehouse model
- [ ] Scheduling and pipeline DAGs
- [ ] Alembic migrations, auth / API keys, multi-user, encrypted connection passwords
- [ ] Production web build (nginx) and PWA manifest

## Security notes (current state)

Spadesys is a local, single-user demo for now:

- There's no login, and anyone who can reach the ports can use the API.
- Saved database connection passwords are stored in plain text in Spadesys's Postgres and in CloudBeaver's workspace.

Use it with development databases and credentials only.

## Notes

MinIO stopped publishing official container images in late 2025. Compose uses [`pgsty/minio`](https://hub.docker.com/r/pgsty/minio), a maintained community build. Spadesys only speaks the S3 API (boto3), so any S3-compatible store works: set `S3_ENDPOINT` and the credentials.

## Authors

Built as equal partners by:

- **Derek Augustine** ([dkaugustine-git](https://github.com/dkaugustine-git)): architect, product and UX design, direction, testing
- **Claude** (Anthropic's AI, via Claude Code): engineering, code and design

This is openly an AI-assisted ("vibe-coded") project. We worked through it together in conversation: Derek designed the architecture (the stack, the Doris hybrid warehouse model) and shaped how it should work and feel, and Claude wrote most of the code. Commits made in those sessions carry a `Co-Authored-By: Claude` line.

## License

Apache 2.0. See [LICENSE](LICENSE).
