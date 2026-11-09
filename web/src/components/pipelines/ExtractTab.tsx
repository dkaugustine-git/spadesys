import { useRef, useState } from "react";
import { api, type ExtractDetail, type Layout } from "../../api";
import { usePoll } from "../../hooks";
import { num } from "../../format";
import { ActivityFeed } from "../ActivityFeed";
import { StatusPill } from "../StatusPill";
import { FileLayout, SampleLayout } from "./FileLayout";
import { FilesList, LoadsTable, PlaceFields, newPlace, placeBody, placeIcon, useAct, whereText } from "./parts";

/** Extracts: where data comes from, and the raw table it lands in. Pipelines reuse them. */
export function ExtractTab({ selected, select, onOpenTable, onOpenPipeline }: {
  selected: string | null;
  select: (id: string | null) => void;
  onOpenTable: (sourceId: string) => void;
  onOpenPipeline: (id: string) => void;
}) {
  const list = usePoll(api.extracts, 3000);
  const [creating, setCreating] = useState(false);
  const showNew = creating || (list.data?.length === 0 && !selected);

  return (
    <main className={`layout pipelines ${selected || showNew ? "has-selection" : ""}`}>
      <section className="panel sources">
        <div className="panel-head">
          <h2>Extracts</h2>
          <span className="muted">{list.data ? list.data.length : "…"}</span>
        </div>
        <p className="muted small">
          An extract is where data comes from: a folder on this computer or in storage. Each file that shows up lands,
          untouched, in a raw table. Build one here and reuse it in as many pipelines as you like.
        </p>
        <button className="btn full" onClick={() => { setCreating(true); select(null); }}>+ New extract</button>
        {list.error && <p className="error">{list.error}</p>}
        <ul className="source-list">
          {list.data?.map((x) => (
            <li key={x.id}>
              <button className={`source-item ${selected === x.id ? "selected" : ""}`} onClick={() => { select(x.id); setCreating(false); }}>
                <div className="source-row">
                  <span className="source-name">{x.name}</span>
                  <StatusPill status={x.last_run?.status} />
                </div>
                <div className="source-meta">
                  <span>{placeIcon(x.kind)} {x.kind === "storage" ? x.prefix : x.folder}</span>
                  <span>→</span>
                  <code>{x.table ? `raw.${x.table.table_name}` : "no table"}</code>
                  {x.waiting > 0 && <span className="tag">{x.waiting} waiting</span>}
                  {x.used_by.length > 0 && <span className="tag">in {x.used_by.length} pipeline{x.used_by.length === 1 ? "" : "s"}</span>}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {showNew ? (
        <NewExtract
          onCancel={list.data?.length ? () => setCreating(false) : undefined}
          onCreated={(x) => { setCreating(false); list.refresh(); select(x.id); }}
        />
      ) : selected ? (
        <ExtractView key={selected} id={selected} onBack={() => select(null)} onOpenTable={onOpenTable}
          onOpenPipeline={onOpenPipeline} onDeleted={() => { select(null); list.refresh(); }} onChanged={list.refresh} />
      ) : (
        <section className="panel empty-state">
          <p className="muted">Pick an extract on the left to see where its files come from, what's waiting, and every load it has done.</p>
        </section>
      )}
    </main>
  );
}

function NewExtract({ onCreated, onCancel }: { onCreated: (x: ExtractDetail) => void; onCancel?: () => void }) {
  const [name, setName] = useState("");
  const [place, setPlace] = useState(newPlace());
  const [layout, setLayout] = useState<Layout | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setErr(null);
    try {
      onCreated(await api.createExtract({ name, ...placeBody(place, name), layout }));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel pipeline-form">
      <div className="panel-head"><h2>New extract</h2></div>
      <div className="step">
        <span className="step-n">1</span>
        <div>
          <h3>Name it</h3>
          <input className="text-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Billing customer export" autoFocus />
        </div>
      </div>
      <div className="step">
        <span className="step-n">2</span>
        <div><PlaceFields name={name} value={place} onChange={setPlace} /></div>
      </div>
      <div className="step">
        <span className="step-n">3</span>
        <div>
          <h3>Where the table is in each file <span className="tag">optional</span></h3>
          <SampleLayout value={layout} onChange={setLayout} />
        </div>
      </div>
      <p className="muted small">An extract runs when you click Run now, or when a pipeline that uses it runs. To have it watch on its own, put it in a pipeline.</p>
      {err && <p className="error">{err}</p>}
      <div className="row-gap">
        <button className="btn" disabled={!name.trim() || busy} onClick={create}>{busy ? "Creating…" : "Create extract"}</button>
        {onCancel && <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>}
      </div>
    </section>
  );
}

function ExtractView({ id, onBack, onDeleted, onChanged, onOpenTable, onOpenPipeline }: {
  id: string; onBack: () => void; onDeleted: () => void; onChanged: () => void;
  onOpenTable: (sourceId: string) => void; onOpenPipeline: (id: string) => void;
}) {
  const { data: x, error, refresh } = usePoll(() => api.extract(id), 2000, [id]);
  const [tab, setTab] = useState<"activity" | "files" | "loads">("activity");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { busy, msg, setMsg, act } = useAct(() => { refresh(); onChanged(); });
  const fileInput = useRef<HTMLInputElement>(null);

  if (error) return <section className="panel"><p className="error">{error}</p></section>;
  if (!x) return <section className="panel"><p className="muted">Loading…</p></section>;
  const waiting = x.files_waiting.filter((f) => f.matches).length;

  return (
    <section className="panel detail">
      <button className="btn btn-link back" onClick={onBack}>← All extracts</button>
      <div className="detail-head">
        <div>
          <h2>{x.name}</h2>
          <div className="flow">
            <span className="flow-box">{placeIcon(x.kind)} <code>{whereText(x)}</code><span className="muted small"> {x.pattern}</span></span>
            <span className="flow-arrow">→</span>
            {x.table ? (
              <button className="flow-box linkish" onClick={() => onOpenTable(x.table!.source_id)} title="Open this table">
                🗄 <code>raw.{x.table.table_name}</code><span className="muted small"> {num(x.table.row_count)} rows</span>
              </button>
            ) : <span className="flow-box error small">raw table was deleted</span>}
          </div>
        </div>
        <div className="row-gap">
          <button className="btn" disabled={!!busy} onClick={() => act("run", async () => {
            const runs = await api.runExtract(x.id);
            return runs.length ? `Picked up ${runs.length} file${runs.length === 1 ? "" : "s"}. Watch the activity below.` : "No new files.";
          })}>{busy === "run" ? "Checking…" : "Run now"}</button>
          <button className="btn btn-secondary" disabled={!!busy} onClick={() => fileInput.current?.click()}>Add a file…</button>
          <input ref={fileInput} type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods" multiple hidden onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) act("add", async () => {
              for (const f of files) await api.addExtractFile(x.id, f);
              return `Added ${files.length} file${files.length === 1 ? "" : "s"}. Click Run now to load, or let a watching pipeline pick ${files.length === 1 ? "it" : "them"} up.`;
            });
          }} />
        </div>
      </div>

      <p className="muted small used-by">
        {x.used_by.length === 0 ? "Not used by any pipeline yet." : <>Used by {x.used_by.map((u, i) => (
          <span key={u.id}>{i > 0 && ", "}<button className="btn btn-link" onClick={() => onOpenPipeline(u.id)}>{u.name}</button>
            {u.mode === "watch" && <span className="muted"> (watching)</span>}</span>
        ))}</>}
      </p>

      <FileLayout x={x} onSaved={() => { refresh(); onChanged(); }} />

      {msg && <p className={msg.ok ? "ok-note" : "error"}>{msg.text}</p>}

      <div className="tabs">
        <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>What happened</button>
        <button className={tab === "files" ? "active" : ""} onClick={() => setTab("files")}>Files{waiting ? ` (${waiting} waiting)` : ""}</button>
        <button className={tab === "loads" ? "active" : ""} onClick={() => setTab("loads")}>Loads ({x.runs.length})</button>
      </div>
      {tab === "activity" && <ActivityFeed extractId={x.id} compact />}
      {tab === "files" && <FilesList p={x} />}
      {tab === "loads" && <LoadsTable runs={x.runs} />}

      <div className="danger-zone">
        {x.used_by.length > 0 ? (
          <p className="muted small">To delete this extract, first delete the pipelines that use it.</p>
        ) : confirmDelete ? (
          <p>
            Delete this extract? Its raw table, folder and archived files stay.{" "}
            <button className="btn btn-danger" onClick={() => api.deleteExtract(x.id).then(onDeleted, (e) => setMsg({ ok: false, text: String(e) }))}>Delete extract</button>{" "}
            <button className="btn btn-secondary" onClick={() => setConfirmDelete(false)}>Keep it</button>
          </p>
        ) : (
          <button className="btn btn-link" onClick={() => setConfirmDelete(true)}>Delete extract…</button>
        )}
      </div>
    </section>
  );
}
