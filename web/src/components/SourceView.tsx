import { useRef, useState } from "react";
import { api, isActive, type SourceDetail } from "../api";
import { usePoll } from "../hooks";
import { ago, cell, duration, num } from "../format";
import { StatusPill } from "./StatusPill";
import { ActivityFeed } from "./ActivityFeed";

type Tab = "activity" | "schema" | "data" | "runs";
const TAB_LABELS: Record<Tab, string> = { activity: "What happened", schema: "Columns", data: "Data", runs: "Loads" };

interface Props {
  id: string;
  onBack: () => void;
  onDeleted: () => void;
  onChanged: () => void;
}

export function SourceView({ id, onBack, onDeleted, onChanged }: Props) {
  const [tab, setTab] = useState<Tab>("activity");
  const [polling, setPolling] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const reloadInput = useRef<HTMLInputElement>(null);

  const detail = usePoll(() => api.source(id), polling ? 1500 : null, [id]);
  const s = detail.data;
  const active = isActive(s?.last_run);
  if (s && active !== polling) setPolling(active);

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      setPolling(true);
      detail.refresh();
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  if (detail.error) return <section className="panel"><p className="error">{detail.error}</p></section>;
  if (!s) return <section className="panel"><p className="muted">Loading…</p></section>;

  return (
    <section className="panel detail">
      <button className="btn btn-link back" onClick={onBack}>← Back to activity</button>
      <div className="detail-head">
        <div>
          <h2>{s.name}</h2>
          <div className="source-meta">
            <code>raw.{s.table_name}</code>
            <span>{num(s.row_count)} rows</span>
            <span>{s.inferred_schema?.columns.length ?? "—"} columns</span>
            <StatusPill status={s.last_run?.status} />
          </div>
        </div>
        <div className="actions">
          <input
            ref={reloadInput}
            type="file"
            accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) act(() => api.reload(s.id, f));
            }}
          />
          <button className="btn btn-secondary" onClick={() => reloadInput.current?.click()}>Load new file</button>
          {confirmDelete ? (
            <span className="confirm">
              Drop table too?
              <button className="btn btn-danger" onClick={() => act(() => api.deleteSource(s.id)).then(onDeleted)}>Delete</button>
              <button className="btn btn-link" onClick={() => setConfirmDelete(false)}>Cancel</button>
            </span>
          ) : (
            <button className="btn btn-ghost" onClick={() => setConfirmDelete(true)}>Delete</button>
          )}
        </div>
      </div>

      {err && <p className="error">{err}</p>}
      {s.last_run?.status === "failed" && <p className="error">Last run failed: {s.last_run.error}</p>}
      {s.last_run?.stats?.warnings.map((w) => <p className="warn" key={w}>⚠ {w}</p>)}

      <nav className="tabs" role="tablist">
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {TAB_LABELS[t]}{t === "runs" ? ` (${s.runs.length})` : ""}
          </button>
        ))}
      </nav>

      {tab === "activity" && <ActivityFeed sourceId={s.id} compact />}
      {tab === "schema" && <SchemaTab s={s} />}
      {tab === "data" && <DataTab id={s.id} version={s.row_count} />}
      {tab === "runs" && <RunsTab s={s} onRetry={(runId) => act(() => api.retry(runId))} />}
    </section>
  );
}

function SchemaTab({ s }: { s: SourceDetail }) {
  const schema = s.inferred_schema;
  if (!schema) return <p className="muted pad">Schema appears after the first successful run.</p>;
  return (
    <>
      {schema.key_candidates.length > 0 && (
        <p className="muted pad">
          Key candidates: {schema.key_candidates.map((k) => <code key={k} className="chip">{k}</code>)}
        </p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Column</th><th>Type</th><th>Nulls</th><th className="num">Distinct</th><th>Samples</th></tr>
          </thead>
          <tbody>
            {schema.columns.map((c) => (
              <tr key={c.name}>
                <td>
                  <code>{c.name}</code>
                  {c.unique && <span className="tag">unique</span>}
                  {c.original_name !== c.name && <div className="muted small">from “{c.original_name}”</div>}
                </td>
                <td><span className={`type type-${c.type}`}>{c.type}</span></td>
                <td>{c.nullable ? `${num(c.null_count)} null` : <span className="muted">not null</span>}</td>
                <td className="num">{num(c.distinct_count)}</td>
                <td className="samples">{c.samples.join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DataTab({ id, version }: { id: string; version: number }) {
  const { data, error } = usePoll(() => api.preview(id, 100), null, [id, version]);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted pad">Loading…</p>;
  if (!data.columns.length) return <p className="muted pad">No data loaded yet.</p>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr>{data.columns.map((c) => <th key={c} className={c.startsWith("_") ? "sys" : ""}>{c}</th>)}</tr></thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j} className={data.columns[j].startsWith("_") ? "sys" : ""} title={cell(v)}>
                  {v === null ? <span className="null">null</span> : cell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small pad">Showing the latest {data.rows.length} rows. System columns are greyed.</p>
    </div>
  );
}

function RunsTab({ s, onRetry }: { s: SourceDetail; onRetry: (runId: string) => void }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>Status</th><th>File</th><th className="num">Read</th><th className="num">Inserted</th><th className="num">Already loaded</th><th>Duration</th><th>When</th><th /></tr>
        </thead>
        <tbody>
          {s.runs.map((r) => (
            <tr key={r.id}>
              <td><StatusPill status={r.status} /></td>
              <td className="samples" title={r.error ?? ""}>{r.original_filename}{r.error && <div className="error small">{r.error}</div>}</td>
              <td className="num">{r.stats ? num(r.stats.rows_read) : "—"}</td>
              <td className="num">{r.stats ? num(r.stats.rows_inserted) : "—"}</td>
              <td className="num">{r.stats ? num(r.stats.rows_already_loaded) : "—"}</td>
              <td>{duration(r.started_at, r.finished_at)}</td>
              <td>{ago(r.created_at)}</td>
              <td>{r.status === "failed" && <button className="btn btn-link" onClick={() => onRetry(r.id)}>Retry</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
