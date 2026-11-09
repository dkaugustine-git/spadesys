import { useState } from "react";
import { api, type ExtractIn, type PipelineFile, type Run, type Source } from "../../api";
import { usePoll } from "../../hooks";
import { ago, human, num } from "../../format";
import { StatusPill } from "../StatusPill";

/* ------------------------------------------------------------ where files show up (the extract form) */

export interface PlaceDraft {
  kind: "folder" | "storage";
  bucket: string; // "" = Spadesys's own bucket
  prefix: string; // "" = incoming/<name>/
  pattern: string;
  table: "new" | string; // "new" or a source id
  tableName: string;
}

export const newPlace = (prefill?: { bucket: string; prefix: string } | null): PlaceDraft => ({
  kind: prefill ? "storage" : "folder",
  bucket: prefill?.bucket ?? "",
  prefix: prefill?.prefix ?? "",
  pattern: "*.csv",
  table: "new",
  tableName: "",
});

export const slugOf = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "…";

/** The draft as the fields POST /extracts wants. */
export function placeBody(d: PlaceDraft, name: string): Omit<ExtractIn, "name"> {
  return {
    kind: d.kind,
    pattern: d.pattern,
    ...(d.kind === "storage" ? { bucket: d.bucket || undefined, prefix: d.prefix.trim() || undefined } : {}),
    ...(d.table === "new" ? { new_table_name: d.tableName.trim() || name } : { source_id: d.table }),
  };
}

/** Pick where files come from, which files, and the raw table they land in. */
export function PlaceFields({ name, value: d, onChange }: { name: string; value: PlaceDraft; onChange: (d: PlaceDraft) => void }) {
  const sources = usePoll(api.sources, null);
  const buckets = usePoll(api.buckets, null);
  const set = (patch: Partial<PlaceDraft>) => onChange({ ...d, ...patch });
  const slug = slugOf(name);
  const bucket = d.bucket || buckets.data?.default || "landing";
  const prefix = (d.prefix.trim() || `incoming/${slug}`).replace(/^\/+|\/+$/g, "") + "/";

  return (
    <>
      <h4>Where files show up</h4>
      <label className="radio">
        <input type="radio" checked={d.kind === "folder"} onChange={() => set({ kind: "folder" })} />
        <span>A folder on this computer: <code>data\inbox\{slug}</code> inside your Spadesys folder. Drop files there from Windows Explorer.</span>
      </label>
      <label className="radio">
        <input type="radio" checked={d.kind === "storage"} onChange={() => set({ kind: "storage" })} />
        <span>A folder in storage (MinIO): files that land there from anywhere, like an upload, a script, or another system using S3.</span>
      </label>
      {d.kind === "storage" && (
        <div className="storage-pick">
          <select className="text-input" value={bucket} onChange={(e) => set({ bucket: e.target.value })}>
            {(buckets.data?.buckets ?? [bucket]).map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <span className="muted">/</span>
          <input className="text-input" value={d.prefix} onChange={(e) => set({ prefix: e.target.value })} placeholder={`incoming/${slug}`} />
        </div>
      )}
      <label className="field">
        <span>Only pick up files named like</span>
        <input className="text-input" value={d.pattern} onChange={(e) => set({ pattern: e.target.value })} />
        <span className="muted small">* means “anything”. <code>*.csv</code> = every CSV, <code>orders_*.csv</code> = only files starting with orders_, <code>*.xlsx</code> = Excel files.</span>
      </label>

      <p className="muted small">CSV, TSV, Excel (.xlsx, .xls) and OpenDocument (.ods) files all work.</p>

      <h4>Raw table it lands in</h4>
      <select className="text-input" value={d.table} onChange={(e) => set({ table: e.target.value })}>
        <option value="new">A new table</option>
        {sources.data?.map((s: Source) => (
          <option key={s.id} value={s.id}>Existing: {s.name} (raw.{s.table_name}, {num(s.row_count)} rows)</option>
        ))}
      </select>
      {d.table === "new" && (
        <input className="text-input" value={d.tableName} onChange={(e) => set({ tableName: e.target.value })}
          placeholder={name ? `Table name (default: ${name})` : "Table name"} />
      )}
      <p className="muted small">
        Raw tables keep the data exactly as it arrived. Same file twice? Rows already there are recognized and skipped.
        {d.kind === "storage"
          ? <> After loading, the file moves from <code>{bucket}/{prefix}</code> to <code>archive/{slug}/</code> so it's never loaded twice.</>
          : <> After loading, a copy is kept in storage under <code>archive/{slug}/</code> and the file moves to <code>data\inbox\{slug}\_done</code>.</>}
        {" "}Nothing is deleted.
      </p>
    </>
  );
}

/* ------------------------------------------------------------ shared views */

interface Place {
  kind: "folder" | "storage" | null;
  folder?: string;
  location?: string;
  bucket?: string | null;
  prefix?: string | null;
  pattern?: string;
  files_waiting: PipelineFile[];
  files_done: PipelineFile[];
}

export const whereText = (p: { kind?: string | null; bucket?: string | null; prefix?: string | null; location?: string }) =>
  p.kind === "storage" ? `${p.bucket}/${p.prefix}` : p.location ?? "";

export const placeIcon = (kind?: string | null) => (kind === "storage" ? "🪣" : "📁");

export function FilesList({ p }: { p: Place }) {
  const waiting = p.files_waiting.filter((f) => f.matches);
  const ignored = p.files_waiting.filter((f) => !f.matches);
  return (
    <div className="files">
      <h3>Waiting</h3>
      {waiting.length === 0 ? (
        <p className="muted small">Nothing waiting. {p.kind === "storage" ? "Put a file in" : "Drop a file into"} <code>{whereText(p)}</code> or click “Add a file…”.</p>
      ) : (
        <ul className="plain">{waiting.map((f) => <li key={f.name}><code>{f.name}</code> <span className="muted small">{human(f.size)} · {ago(f.modified)}</span></li>)}</ul>
      )}
      {ignored.length > 0 && (
        <>
          <h3>There but not picked up</h3>
          <p className="muted small">These don't match <code>{p.pattern}</code>.</p>
          <ul className="plain">{ignored.map((f) => <li key={f.name}><code>{f.name}</code></li>)}</ul>
        </>
      )}
      <h3>{p.kind === "storage" ? <>Done (moved to <code>archive/{p.folder}/</code>)</> : <>Done (moved to <code>_done</code>)</>}</h3>
      {p.files_done.length === 0 ? <p className="muted small">None yet.</p> : (
        <ul className="plain">{p.files_done.map((f) => <li key={f.path}><code>{f.path}</code> <span className="muted small">{human(f.size)}</span></li>)}</ul>
      )}
      <p className="muted small">A copy of every loaded file is also kept on the Storage tab under <code>archive/{p.folder}/</code>.</p>
    </div>
  );
}

export function LoadsTable({ runs }: { runs: Run[] }) {
  if (!runs.length) return <p className="muted small">No loads yet.</p>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th>File</th><th>Status</th><th>New rows</th><th>Already there</th><th>When</th></tr></thead>
        <tbody>
          {runs.map((r) => (
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
    </div>
  );
}

/** Busy flag + a success/error note around an async button action. */
export function useAct(after: () => void) {
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function act(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setMsg(null);
    try {
      const text = await fn();
      if (text) setMsg({ ok: true, text });
      after();
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(null);
    }
  }
  return { busy, msg, setMsg, act };
}
