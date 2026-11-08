import { useRef, useState } from "react";
import { api, type PipelineDetail, type PipelineIn, type Source } from "../api";
import { usePoll } from "../hooks";
import { ago, human, num } from "../format";
import { ActivityFeed } from "./ActivityFeed";
import { StatusPill } from "./StatusPill";

/** Pipelines: a folder where files show up -> a table. Run on demand, or let it watch. */
export type StoragePlace = { bucket: string; prefix: string };

export function PipelinesPage({ onOpenTable, prefill, onPrefillUsed }: {
  onOpenTable: (sourceId: string) => void;
  prefill?: StoragePlace | null; // "Watch this folder with a pipeline" from the Storage tab
  onPrefillUsed?: () => void;
}) {
  const list = usePoll(api.pipelines, 3000);
  // #/pipelines/<id> opens that pipeline directly (bookmarkable).
  const [selected, setSelectedState] = useState<string | null>(() => window.location.hash.split("/")[2] || null);
  const setSelected = (id: string | null) => {
    setSelectedState(id);
    history.replaceState(null, "", id ? `#/pipelines/${id}` : "#/pipelines");
  };
  const [creating, setCreating] = useState(!!prefill);

  const showNew = creating || (list.data?.length === 0 && !selected);

  return (
    <main className={`layout pipelines ${selected || showNew ? "has-selection" : ""}`}>
      <section className="panel sources">
        <div className="panel-head">
          <h2>Pipelines</h2>
          <span className="muted">{list.data ? list.data.length : "…"}</span>
        </div>
        <p className="muted small">
          A pipeline watches a folder on this computer or in storage. Each file that shows up is loaded into a table, then archived so it never loads twice.
        </p>
        <button className="btn full" onClick={() => { setCreating(true); setSelected(null); }}>+ New pipeline</button>
        {list.error && <p className="error">{list.error}</p>}
        <ul className="source-list">
          {list.data?.map((p) => (
            <li key={p.id}>
              <button className={`source-item ${selected === p.id ? "selected" : ""}`} onClick={() => { setSelected(p.id); setCreating(false); }}>
                <div className="source-row">
                  <span className="source-name">{p.name}</span>
                  {p.mode === "watch" ? <span className="pill pill-running">watching</span> : <StatusPill status={p.last_run?.status} />}
                </div>
                <div className="source-meta">
                  <span>{p.source_kind === "storage" ? `🪣 ${p.prefix}` : `📁 ${p.folder}`}</span>
                  <span>→</span>
                  <code>{p.destination ? `raw.${p.destination.table_name}` : "no table"}</code>
                  {p.waiting > 0 && <span className="tag">{p.waiting} waiting</span>}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {showNew ? (
        <NewPipeline
          key={prefill ? `${prefill.bucket}/${prefill.prefix}` : "new"}
          prefill={prefill ?? null}
          onCancel={list.data?.length ? () => { setCreating(false); onPrefillUsed?.(); } : undefined}
          onCreated={(p) => { setCreating(false); onPrefillUsed?.(); list.refresh(); setSelected(p.id); }}
        />
      ) : selected ? (
        <PipelineView key={selected} id={selected} onBack={() => setSelected(null)} onOpenTable={onOpenTable}
          onDeleted={() => { setSelected(null); list.refresh(); }} onChanged={list.refresh} />
      ) : (
        <section className="panel empty-state">
          <p className="muted">Pick a pipeline on the left to see its folder, the files waiting, and every load it has done.</p>
        </section>
      )}
    </main>
  );
}

/* ------------------------------------------------------------ new pipeline */

function NewPipeline({ onCreated, onCancel, prefill }: {
  onCreated: (p: PipelineDetail) => void; onCancel?: () => void; prefill: StoragePlace | null;
}) {
  const sources = usePoll(api.sources, null);
  const buckets = usePoll(api.buckets, null);
  const [kind, setKind] = useState<"folder" | "storage">(prefill ? "storage" : "folder");
  const [bucket, setBucket] = useState(prefill?.bucket ?? "");
  const [prefix, setPrefix] = useState(prefill?.prefix ?? "");
  const [name, setName] = useState("");
  const [pattern, setPattern] = useState("*.csv");
  const [dest, setDest] = useState<"new" | string>("new");
  const [tableName, setTableName] = useState("");
  const [mode, setMode] = useState<"manual" | "watch">("watch");
  const [seconds, setSeconds] = useState(10);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "…";
  const theBucket = bucket || buckets.data?.default || "landing";
  const thePrefix = (prefix.trim() || `incoming/${slug}`).replace(/^\/+|\/+$/g, "") + "/";

  async function create() {
    setBusy(true);
    setErr(null);
    const body: PipelineIn = {
      name, pattern, mode, watch_seconds: seconds, source_kind: kind,
      ...(kind === "storage" ? { bucket: theBucket, prefix: thePrefix } : {}),
      ...(dest === "new" ? { new_table_name: tableName || name } : { destination_source_id: dest }),
    };
    try {
      onCreated(await api.createPipeline(body));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel pipeline-form">
      <div className="panel-head"><h2>New pipeline</h2></div>

      <div className="step">
        <span className="step-n">1</span>
        <div>
          <h3>Name it</h3>
          <input className="text-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Daily orders" autoFocus />
        </div>
      </div>

      <div className="step">
        <span className="step-n">2</span>
        <div>
          <h3>Where files show up</h3>
          <label className="radio">
            <input type="radio" checked={kind === "folder"} onChange={() => setKind("folder")} />
            <span>A folder on this computer: <code>data\inbox\{slug}</code> inside your Spadesys folder.
              Drop files there from Windows Explorer.</span>
          </label>
          <label className="radio">
            <input type="radio" checked={kind === "storage"} onChange={() => setKind("storage")} />
            <span>A folder in storage (MinIO): files that land there from anywhere, like an upload, a script, or another system using S3.</span>
          </label>
          {kind === "storage" && (
            <div className="storage-pick">
              <select className="text-input" value={theBucket} onChange={(e) => setBucket(e.target.value)}>
                {(buckets.data?.buckets ?? [theBucket]).map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
              <span className="muted">/</span>
              <input className="text-input" value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder={`incoming/${slug}`} />
            </div>
          )}
          <p className="muted small">Either way, “Add a file…” on the pipeline page puts a file there for you.</p>
          <label className="field">
            <span>Only pick up files named like</span>
            <input className="text-input" value={pattern} onChange={(e) => setPattern(e.target.value)} />
            <span className="muted small">* means “anything”. <code>*.csv</code> = every CSV, <code>orders_*.csv</code> = only files starting with orders_.</span>
          </label>
        </div>
      </div>

      <div className="step">
        <span className="step-n">3</span>
        <div>
          <h3>Where the rows go</h3>
          <select className="text-input" value={dest} onChange={(e) => setDest(e.target.value)}>
            <option value="new">A new table</option>
            {sources.data?.map((s: Source) => (
              <option key={s.id} value={s.id}>Existing: {s.name} (raw.{s.table_name}, {num(s.row_count)} rows)</option>
            ))}
          </select>
          {dest === "new" && (
            <input className="text-input" value={tableName} onChange={(e) => setTableName(e.target.value)} placeholder={name ? `Table name (default: ${name})` : "Table name"} />
          )}
          <p className="muted small">Same file twice? Rows already in the table are recognized and skipped, so nothing doubles up.</p>
        </div>
      </div>

      <div className="step">
        <span className="step-n">4</span>
        <div>
          <h3>When it runs</h3>
          <label className="radio">
            <input type="radio" checked={mode === "watch"} onChange={() => setMode("watch")} />
            <span>Watch the folder: check every
              <input className="text-input inline-num" type="number" min={5} max={3600} value={seconds} onChange={(e) => setSeconds(Number(e.target.value) || 10)} />
              seconds and load new files by itself</span>
          </label>
          <label className="radio">
            <input type="radio" checked={mode === "manual"} onChange={() => setMode("manual")} />
            <span>Only when I click “Run now”</span>
          </label>
        </div>
      </div>

      <div className="step">
        <span className="step-n">5</span>
        <div>
          <h3>After a file loads</h3>
          {kind === "storage" ? (
            <p className="muted small">
              The file moves from <code>{theBucket}/{thePrefix}</code> to <code>archive/{slug}/</code> in storage, so it's never loaded twice. Nothing is deleted.
            </p>
          ) : (
            <p className="muted small">
              A copy is kept in storage under <code>archive/{slug}/</code>, and the file moves to <code>data\inbox\{slug}\_done</code>. Nothing is deleted.
            </p>
          )}
        </div>
      </div>

      {err && <p className="error">{err}</p>}
      <div className="row-gap">
        <button className="btn" disabled={!name.trim() || busy} onClick={create}>{busy ? "Creating…" : "Create pipeline"}</button>
        {onCancel && <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ one pipeline */

const where = (p: PipelineDetail) => (p.source_kind === "storage" ? `${p.bucket}/${p.prefix}` : p.location);

function PipelineView({ id, onBack, onDeleted, onChanged, onOpenTable }: {
  id: string; onBack: () => void; onDeleted: () => void; onChanged: () => void; onOpenTable: (sourceId: string) => void;
}) {
  const { data: p, error, refresh } = usePoll(() => api.pipeline(id), 2000, [id]);
  const [tab, setTab] = useState<"activity" | "files" | "loads">("activity");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function act(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setMsg(null);
    try {
      const text = await fn();
      if (text) setMsg({ ok: true, text });
      refresh();
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(null);
    }
  }

  if (error) return <section className="panel"><p className="error">{error}</p></section>;
  if (!p) return <section className="panel"><p className="muted">Loading…</p></section>;

  const waiting = p.files_waiting.filter((f) => f.matches);
  const ignored = p.files_waiting.filter((f) => !f.matches);

  return (
    <section className="panel detail">
      <button className="btn btn-link back" onClick={onBack}>← All pipelines</button>
      <div className="detail-head">
        <div>
          <h2>{p.name}</h2>
          <div className="flow">
            <span className="flow-box">{p.source_kind === "storage" ? "🪣" : "📁"} <code>{where(p)}</code><span className="muted small"> {p.pattern}</span></span>
            <span className="flow-arrow">→</span>
            {p.destination ? (
              <button className="flow-box linkish" onClick={() => onOpenTable(p.destination!.source_id)} title="Open this table">
                🗄 <code>raw.{p.destination.table_name}</code><span className="muted small"> {num(p.destination.row_count)} rows</span>
              </button>
            ) : (
              <span className="flow-box error small">destination table was deleted</span>
            )}
          </div>
        </div>
        <div className="row-gap">
          <button className="btn" disabled={!!busy} onClick={() => act("run", async () => {
            const runs = await api.runPipeline(p.id);
            return runs.length ? `Picked up ${runs.length} file${runs.length === 1 ? "" : "s"}. Watch the activity below.` : "No new files in the folder.";
          })}>{busy === "run" ? "Checking…" : "Run now"}</button>
          <button className="btn btn-secondary" disabled={!!busy} onClick={() => fileInput.current?.click()}>Add a file…</button>
          <input ref={fileInput} type="file" accept=".csv,.tsv,.txt" multiple hidden onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) act("add", async () => {
              for (const f of files) await api.addPipelineFile(p.id, f);
              return `Added ${files.length} file${files.length === 1 ? "" : "s"} to the folder.` + (p.mode === "watch" ? " It'll be picked up in a few seconds." : " Click Run now to load.");
            });
          }} />
        </div>
      </div>

      <div className="watch-row">
        <label className="switch">
          <input type="checkbox" checked={p.mode === "watch"} disabled={!!busy}
            onChange={(e) => act("mode", () => api.updatePipeline(p.id, { mode: e.target.checked ? "watch" : "manual" }).then(() => undefined))} />
          <span>{p.mode === "watch"
            ? <>Watching: checks the folder every {p.watch_seconds}s{p.last_checked_at ? <span className="muted"> · last checked {ago(p.last_checked_at)}</span> : null}</>
            : "Not watching: runs only when you click Run now"}</span>
        </label>
      </div>

      {msg && <p className={msg.ok ? "ok-note" : "error"}>{msg.text}</p>}

      <div className="tabs">
        <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>What happened</button>
        <button className={tab === "files" ? "active" : ""} onClick={() => setTab("files")}>
          Files{waiting.length ? ` (${waiting.length} waiting)` : ""}
        </button>
        <button className={tab === "loads" ? "active" : ""} onClick={() => setTab("loads")}>Loads ({p.runs.length})</button>
      </div>

      {tab === "activity" && <ActivityFeed pipelineId={p.id} compact />}

      {tab === "files" && (
        <div className="files">
          <h3>Waiting in the folder</h3>
          {waiting.length === 0 ? <p className="muted small">Nothing waiting. {p.source_kind === "storage" ? "Put a file in" : "Drop a file into"} <code>{where(p)}</code> or click “Add a file…”.</p> : (
            <ul className="plain">{waiting.map((f) => <li key={f.name}><code>{f.name}</code> <span className="muted small">{human(f.size)} · {ago(f.modified)}</span></li>)}</ul>
          )}
          {ignored.length > 0 && (
            <>
              <h3>In the folder but not picked up</h3>
              <p className="muted small">These don't match <code>{p.pattern}</code>.</p>
              <ul className="plain">{ignored.map((f) => <li key={f.name}><code>{f.name}</code></li>)}</ul>
            </>
          )}
          <h3>{p.source_kind === "storage" ? <>Done (moved to <code>archive/{p.folder}/</code>)</> : <>Done (moved to <code>_done</code>)</>}</h3>
          {p.files_done.length === 0 ? <p className="muted small">None yet.</p> : (
            <ul className="plain">{p.files_done.map((f) => <li key={f.path}><code>{f.path}</code> <span className="muted small">{human(f.size)}</span></li>)}</ul>
          )}
          <p className="muted small">A copy of every loaded file is also kept on the Storage tab under <code>archive/{p.folder}/</code>.</p>
        </div>
      )}

      {tab === "loads" && (
        <div className="table-wrap">
          {p.runs.length === 0 ? <p className="muted small">No loads yet.</p> : (
            <table className="data">
              <thead><tr><th>File</th><th>Status</th><th>New rows</th><th>Already there</th><th>When</th></tr></thead>
              <tbody>
                {p.runs.map((r) => (
                  <tr key={r.id} title={r.error ?? ""}>
                    <td>{r.original_filename}</td>
                    <td><StatusPill status={r.status} /></td>
                    <td>{r.stats ? num(r.stats.rows_inserted) : "—"}</td>
                    <td>{r.stats ? num(r.stats.rows_already_loaded) : "—"}</td>
                    <td>{ago(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="danger-zone">
        {confirmDelete ? (
          <p>
            Delete this pipeline? Its table, folder and archived files stay. {" "}
            <button className="btn btn-danger" onClick={() => api.deletePipeline(p.id).then(onDeleted, (e) => setMsg({ ok: false, text: String(e) }))}>Delete pipeline</button>{" "}
            <button className="btn btn-secondary" onClick={() => setConfirmDelete(false)}>Keep it</button>
          </p>
        ) : (
          <button className="btn btn-link" onClick={() => setConfirmDelete(true)}>Delete pipeline…</button>
        )}
      </div>
    </section>
  );
}
