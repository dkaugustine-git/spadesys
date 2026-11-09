import { useEffect, useRef, useState } from "react";
import { api, type PipelineDetail, type PipelineIn } from "../api";
import { usePoll } from "../hooks";
import { ago, num } from "../format";
import { ActivityFeed } from "./ActivityFeed";
import { StatusPill } from "./StatusPill";
import { ExtractTab } from "./pipelines/ExtractTab";
import { TransformTab } from "./pipelines/TransformTab";
import { FilesList, LoadsTable, PlaceFields, newPlace, placeBody, placeIcon, useAct, whereText } from "./pipelines/parts";

export type StoragePlace = { bucket: string; prefix: string };
type Sub = "pipelines" | "extract" | "transform" | "load";

const SUBS: { key: Sub; label: string; hint: string }[] = [
  { key: "pipelines", label: "Pipelines", hint: "Chain the pieces together and decide when they run" },
  { key: "extract", label: "Extract", hint: "Where data comes from; it lands untouched in a raw table" },
  { key: "transform", label: "Transform", hint: "Reusable changes: split, parse, combine, clean up" },
  { key: "load", label: "Load", hint: "Where finished data goes: a table, Doris, a file, an email" },
];

/** #/pipelines[/<id>] · #/pipelines/extract[/<id>] · #/pipelines/transform · #/pipelines/load */
function fromHash(): { sub: Sub; id: string | null } {
  const [, a, b] = window.location.hash.replace(/^#\/?/, "").split("/");
  if (a === "extract" || a === "transform" || a === "load") return { sub: a, id: b || null };
  return { sub: "pipelines", id: a || null };
}

function toHash(sub: Sub, id: string | null) {
  const path = ["pipelines", sub === "pipelines" ? null : sub, id].filter(Boolean).join("/");
  history.replaceState(null, "", `#/${path}`);
}

/** The ETL workbench: build extracts (transforms and loads next), then orchestrate them as pipelines. */
export function PipelinesPage({ onOpenTable, prefill, onPrefillUsed }: {
  onOpenTable: (sourceId: string) => void;
  prefill?: StoragePlace | null; // "Watch this folder with a pipeline" from the Storage tab
  onPrefillUsed?: () => void;
}) {
  const [{ sub, id }, setRoute] = useState(fromHash);
  const go = (s: Sub, i: string | null = null) => { setRoute({ sub: s, id: i }); toHash(s, i); };

  useEffect(() => { if (prefill && sub !== "pipelines") go("pipelines"); }, [prefill]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="etl">
      <nav className="subtabs" aria-label="Pipeline building blocks">
        {SUBS.map((s, i) => (
          <span key={s.key} className="subtab-wrap">
            {i === 1 && <span className="subtab-sep" aria-hidden>·</span>}
            <button className={sub === s.key ? "active" : ""} title={s.hint} onClick={() => go(s.key)}>{s.label}</button>
          </span>
        ))}
      </nav>
      {sub === "pipelines" && (
        <PipelinesTab selected={id} select={(i) => go("pipelines", i)} onOpenTable={onOpenTable}
          onOpenExtract={(i) => go("extract", i)} prefill={prefill} onPrefillUsed={onPrefillUsed} />
      )}
      {sub === "extract" && (
        <ExtractTab selected={id} select={(i) => go("extract", i)} onOpenTable={onOpenTable} onOpenPipeline={(i) => go("pipelines", i)} />
      )}
      {sub === "transform" && <TransformTab selected={id} select={(i) => go("transform", i)} />}
      {sub === "load" && (
        <Coming title="Load" lead="Where finished data goes. Build a load once, then reuse it in any pipeline.">
          <li><b>A Spadesys table</b> in the <code>clean</code> schema</li>
          <li><b>Doris</b>, the warehouse</li>
          <li><b>A CSV file</b> in storage</li>
          <li><b>Email</b> the file to someone</li>
        </Coming>
      )}
    </div>
  );
}

function Coming({ title, lead, children }: { title: string; lead: string; children: React.ReactNode }) {
  return (
    <main className="layout single">
      <section className="panel coming">
        <h2>{title}</h2>
        <p>{lead}</p>
        <p className="muted small">Coming next:</p>
        <ul className="plain coming-list">{children}</ul>
        <p className="muted small">Until then, data stays as it landed in its raw table, which is always kept.</p>
      </section>
    </main>
  );
}

/* ------------------------------------------------------------ pipelines list */

function PipelinesTab({ selected, select, onOpenTable, onOpenExtract, prefill, onPrefillUsed }: {
  selected: string | null;
  select: (id: string | null) => void;
  onOpenTable: (sourceId: string) => void;
  onOpenExtract: (id: string) => void;
  prefill?: StoragePlace | null;
  onPrefillUsed?: () => void;
}) {
  const list = usePoll(api.pipelines, 3000);
  const [creating, setCreating] = useState(!!prefill);
  useEffect(() => { if (prefill) { setCreating(true); select(null); } }, [prefill]); // eslint-disable-line react-hooks/exhaustive-deps
  const showNew = creating || (list.data?.length === 0 && !selected);

  return (
    <main className={`layout pipelines ${selected || showNew ? "has-selection" : ""}`}>
      <section className="panel sources">
        <div className="panel-head">
          <h2>Pipelines</h2>
          <span className="muted">{list.data ? list.data.length : "…"}</span>
        </div>
        <p className="muted small">
          A pipeline runs the pieces in order: an extract today, with transforms and loads joining soon. Run it on demand, or let it watch for new files.
        </p>
        <button className="btn full" onClick={() => { setCreating(true); select(null); }}>+ New pipeline</button>
        {list.error && <p className="error">{list.error}</p>}
        <ul className="source-list">
          {list.data?.map((p) => (
            <li key={p.id}>
              <button className={`source-item ${selected === p.id ? "selected" : ""}`} onClick={() => { select(p.id); setCreating(false); }}>
                <div className="source-row">
                  <span className="source-name">{p.name}</span>
                  {p.mode === "watch" ? <span className="pill pill-running">watching</span> : <StatusPill status={p.last_run?.status} />}
                </div>
                <div className="source-meta">
                  <span>{placeIcon(p.source_kind)} {p.extract?.name ?? "no extract"}</span>
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
          onCreated={(p) => { setCreating(false); onPrefillUsed?.(); list.refresh(); select(p.id); }}
        />
      ) : selected ? (
        <PipelineView key={selected} id={selected} onBack={() => select(null)} onOpenTable={onOpenTable} onOpenExtract={onOpenExtract}
          onDeleted={() => { select(null); list.refresh(); }} onChanged={list.refresh} />
      ) : (
        <section className="panel empty-state">
          <p className="muted">Pick a pipeline on the left to see its steps, the files waiting, and every load it has done.</p>
        </section>
      )}
    </main>
  );
}

/* ------------------------------------------------------------ new pipeline */

function NewPipeline({ onCreated, onCancel, prefill }: {
  onCreated: (p: PipelineDetail) => void; onCancel?: () => void; prefill: StoragePlace | null;
}) {
  const extracts = usePoll(api.extracts, null);
  const [name, setName] = useState("");
  const [use, setUse] = useState<"new" | string>("new"); // "new" or an extract id
  const [place, setPlace] = useState(newPlace(prefill));
  const [mode, setMode] = useState<"manual" | "watch">("watch");
  const [seconds, setSeconds] = useState(10);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setErr(null);
    let body: PipelineIn = { name, mode, watch_seconds: seconds };
    if (use === "new") {
      const x = placeBody(place, name);
      body = { ...body, source_kind: x.kind, bucket: x.bucket, prefix: x.prefix, pattern: x.pattern,
        destination_source_id: x.source_id, new_table_name: x.new_table_name };
    } else {
      body.extract_id = use;
    }
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
          <h3>Extract: where the data comes from</h3>
          {!!extracts.data?.length && !prefill && (
            <select className="text-input" value={use} onChange={(e) => setUse(e.target.value)}>
              <option value="new">Make a new extract</option>
              {extracts.data.map((x) => (
                <option key={x.id} value={x.id}>Use “{x.name}” ({whereText(x)} → raw.{x.table?.table_name ?? "?"})</option>
              ))}
            </select>
          )}
          {use === "new"
            ? <div className="nested"><PlaceFields name={name} value={place} onChange={setPlace} /></div>
            : <p className="muted small">This pipeline will run that extract. It can still be used by other pipelines and run on its own from the Extract tab.</p>}
        </div>
      </div>

      <div className="step later">
        <span className="step-n">3</span>
        <div>
          <h3>Transform <span className="tag">coming next</span></h3>
          <p className="muted small">Transforms are built on the Transform tab and can be run from there. Running them as part of a pipeline comes next.</p>
        </div>
      </div>

      <div className="step later">
        <span className="step-n">4</span>
        <div>
          <h3>Load <span className="tag">coming next</span></h3>
          <p className="muted small">Send the result to a clean table, Doris, a file or an email. For now the raw table is the result.</p>
        </div>
      </div>

      <div className="step">
        <span className="step-n">5</span>
        <div>
          <h3>When it runs</h3>
          <label className="radio">
            <input type="radio" checked={mode === "watch"} onChange={() => setMode("watch")} />
            <span>Watch for new files: check every
              <input className="text-input inline-num" type="number" min={5} max={3600} value={seconds} onChange={(e) => setSeconds(Number(e.target.value) || 10)} />
              seconds and run by itself</span>
          </label>
          <label className="radio">
            <input type="radio" checked={mode === "manual"} onChange={() => setMode("manual")} />
            <span>Only when I click “Run now”</span>
          </label>
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

function PipelineView({ id, onBack, onDeleted, onChanged, onOpenTable, onOpenExtract }: {
  id: string; onBack: () => void; onDeleted: () => void; onChanged: () => void;
  onOpenTable: (sourceId: string) => void; onOpenExtract: (id: string) => void;
}) {
  const { data: p, error, refresh } = usePoll(() => api.pipeline(id), 2000, [id]);
  const [tab, setTab] = useState<"activity" | "files" | "loads">("activity");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { busy, msg, setMsg, act } = useAct(() => { refresh(); onChanged(); });
  const fileInput = useRef<HTMLInputElement>(null);

  if (error) return <section className="panel"><p className="error">{error}</p></section>;
  if (!p) return <section className="panel"><p className="muted">Loading…</p></section>;
  const waiting = p.files_waiting.filter((f) => f.matches).length;
  const place = { ...p, kind: p.source_kind };

  return (
    <section className="panel detail">
      <button className="btn btn-link back" onClick={onBack}>← All pipelines</button>
      <div className="detail-head">
        <div>
          <h2>{p.name}</h2>
          <div className="flow">
            {p.extract ? (
              <button className="flow-box linkish" onClick={() => onOpenExtract(p.extract!.id)} title="Open this extract">
                <span className="flow-kind">Extract</span>{placeIcon(p.source_kind)} {p.extract.name}
                <span className="muted small"> <code>{whereText(place)}</code> {p.pattern}</span>
              </button>
            ) : <span className="flow-box error small">no extract</span>}
            <span className="flow-arrow">→</span>
            {p.destination ? (
              <button className="flow-box linkish" onClick={() => onOpenTable(p.destination!.source_id)} title="Open this table">
                <span className="flow-kind">Raw table</span>🗄 <code>raw.{p.destination.table_name}</code>
                <span className="muted small"> {num(p.destination.row_count)} rows</span>
              </button>
            ) : <span className="flow-box error small">raw table was deleted</span>}
          </div>
          {p.layout_text && (
            <p className="muted small flow-note">📄 File layout: {p.layout_text}{!p.layout && " (the standard way)"}.{" "}
              {p.extract && <button className="btn btn-link small" onClick={() => onOpenExtract(p.extract!.id)}>Change it on the extract</button>}
            </p>
          )}
        </div>
        <div className="row-gap">
          <button className="btn" disabled={!!busy || !p.extract} onClick={() => act("run", async () => {
            const runs = await api.runPipeline(p.id);
            return runs.length ? `Picked up ${runs.length} file${runs.length === 1 ? "" : "s"}. Watch the activity below.` : "No new files.";
          })}>{busy === "run" ? "Checking…" : "Run now"}</button>
          <button className="btn btn-secondary" disabled={!!busy || !p.extract} onClick={() => fileInput.current?.click()}>Add a file…</button>
          <input ref={fileInput} type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods" multiple hidden onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) act("add", async () => {
              for (const f of files) await api.addPipelineFile(p.id, f);
              return `Added ${files.length} file${files.length === 1 ? "" : "s"}.` + (p.mode === "watch" ? " It'll be picked up in a few seconds." : " Click Run now to load.");
            });
          }} />
        </div>
      </div>

      <div className="watch-row">
        <label className="switch">
          <input type="checkbox" checked={p.mode === "watch"} disabled={!!busy}
            onChange={(e) => act("mode", () => api.updatePipeline(p.id, { mode: e.target.checked ? "watch" : "manual" }).then(() => undefined))} />
          <span>{p.mode === "watch"
            ? <>Watching: checks for new files every {p.watch_seconds}s{p.last_checked_at ? <span className="muted"> · last checked {ago(p.last_checked_at)}</span> : null}</>
            : "Not watching: runs only when you click Run now"}</span>
        </label>
      </div>

      {msg && <p className={msg.ok ? "ok-note" : "error"}>{msg.text}</p>}

      <div className="tabs">
        <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>What happened</button>
        <button className={tab === "files" ? "active" : ""} onClick={() => setTab("files")}>Files{waiting ? ` (${waiting} waiting)` : ""}</button>
        <button className={tab === "loads" ? "active" : ""} onClick={() => setTab("loads")}>Loads ({p.runs.length})</button>
      </div>
      {tab === "activity" && <ActivityFeed pipelineId={p.id} compact />}
      {tab === "files" && <FilesList p={place} />}
      {tab === "loads" && <LoadsTable runs={p.runs} />}

      <div className="danger-zone">
        {confirmDelete ? (
          <p>
            Delete this pipeline? Its extract, raw table and files stay.{" "}
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
