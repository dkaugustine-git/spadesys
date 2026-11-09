import { useEffect, useMemo, useState } from "react";
import {
  api, type ColInfo, type StepOp, type TableInfo, type Transform, type TransformPreview, type TransformStep,
} from "../../api";
import { usePoll } from "../../hooks";
import { ago, num } from "../../format";
import { ActivityFeed } from "../ActivityFeed";
import { slugOf } from "./parts";

const OPS: { op: StepOp; label: string; hint: string }[] = [
  { op: "split", label: "Split a column", hint: "ABC-123-RED → ABC · 123 · RED" },
  { op: "parse_name", label: "Parse names", hint: "“Smith, Jane” or “Jane Smith” → Jane · Smith" },
  { op: "join", label: "Join columns", hint: "Jane + Smith → Jane Smith" },
  { op: "clean", label: "Clean up text", hint: "Trim spaces, fix capitals" },
  { op: "rename", label: "Rename columns", hint: "cust_nm → customer_name" },
  { op: "drop", label: "Remove columns", hint: "Leave out what you don't need" },
  { op: "stack", label: "Stack another table", hint: "Add another table's rows underneath, matching columns" },
  { op: "dedupe", label: "Remove duplicates", hint: "Keep one row per customer, order, …" },
];
const label = (op: string) => OPS.find((o) => o.op === op)?.label ?? op;
const TEXTY = new Set(["text", "character varying", "character"]);

/** Transforms: reusable changes from a raw table to a clean one. Raw data is never changed. */
export function TransformTab({ selected, select }: { selected: string | null; select: (id: string | null) => void }) {
  const list = usePoll(api.transforms, 4000);
  const [creating, setCreating] = useState(false);
  const showNew = creating || (list.data?.length === 0 && !selected);
  const current = list.data?.find((t) => t.id === selected) ?? null;

  return (
    <main className={`layout transforms ${selected || showNew ? "has-selection" : ""}`}>
      <section className="panel sources">
        <div className="panel-head">
          <h2>Transforms</h2>
          <span className="muted">{list.data ? list.data.length : "…"}</span>
        </div>
        <p className="muted small">
          A transform reads a table, changes it step by step, and writes the result to the <code>clean</code> schema.
          The raw table is never touched, so you can change a step and run it again any time.
        </p>
        <button className="btn full" onClick={() => { setCreating(true); select(null); }}>+ New transform</button>
        {list.error && <p className="error">{list.error}</p>}
        <ul className="source-list">
          {list.data?.map((t) => (
            <li key={t.id}>
              <button className={`source-item ${selected === t.id ? "selected" : ""}`} onClick={() => { select(t.id); setCreating(false); }}>
                <div className="source-row">
                  <span className="source-name">{t.name}</span>
                  {t.last_error ? <span className="pill pill-failed">failed</span>
                    : t.last_run_at ? <span className="pill pill-succeeded">{num(t.last_rows ?? 0)} rows</span>
                    : <span className="pill">not run</span>}
                </div>
                <div className="source-meta">
                  <code>{t.input_table}</code><span>→</span><code>{t.output_full}</code>
                  <span className="tag">{t.steps.length} step{t.steps.length === 1 ? "" : "s"}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {showNew ? (
        <Editor key="new" transform={null} onCancel={list.data?.length ? () => setCreating(false) : undefined}
          onSaved={(t) => { setCreating(false); list.refresh(); select(t.id); }} onDeleted={() => {}} />
      ) : current ? (
        <Editor key={current.id} transform={current} onSaved={() => list.refresh()}
          onBack={() => select(null)} onDeleted={() => { select(null); list.refresh(); }} />
      ) : selected && list.data ? (
        <section className="panel"><p className="error">That transform doesn't exist anymore.</p></section>
      ) : (
        <section className="panel empty-state">
          <p className="muted">Pick a transform on the left, or make a new one.</p>
        </section>
      )}
    </main>
  );
}

/* ------------------------------------------------------------ editor */

function newStep(op: StepOp, cols: ColInfo[]): TransformStep {
  const text = cols.find((c) => TEXTY.has(c.type))?.name ?? cols[0]?.name ?? "";
  switch (op) {
    case "split": return { op, column: text, separator: "-", into: [] };
    case "parse_name": return { op, column: cols.find((c) => /name/i.test(c.name))?.name ?? text, first: "first_name", last: "last_name" };
    case "join": return { op, columns: [], separator: " ", into: "", keep_originals: true };
    case "clean": return { op, columns: [], trim: true, case: "none" };
    case "rename": return { op, renames: {} };
    case "drop": return { op, columns: [] };
    case "stack": return { op, table: "", mapping: {}, label_column: "", this_label: "", other_label: "" };
    case "dedupe": return { op, columns: [], ignore_case: true };
  }
}

function Editor({ transform: t, onSaved, onCancel, onBack, onDeleted }: {
  transform: Transform | null; onSaved: (t: Transform) => void; onCancel?: () => void; onBack?: () => void; onDeleted: () => void;
}) {
  const tables = usePoll(api.transformTables, 10000);
  const [name, setName] = useState(t?.name ?? "");
  const [input, setInput] = useState(t?.input_table ?? "");
  const [steps, setSteps] = useState<TransformStep[]>(t?.steps ?? []);
  const [output, setOutput] = useState(t?.output_table ?? "");
  const [preview, setPreview] = useState<TransformPreview | null>(null);
  const [showSql, setShowSql] = useState(false);
  const [tab, setTab] = useState<"build" | "activity">("build");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const outName = output.trim() || slugOf(name).replace("…", "");
  const dirty = !t || name !== t.name || input !== t.input_table || output !== t.output_table || JSON.stringify(steps) !== JSON.stringify(t.steps);

  // Live preview, a moment after the last change.
  const body = JSON.stringify({ input_table: input, steps, output_table: outName });
  useEffect(() => {
    if (!input) { setPreview(null); return; }
    const timer = setTimeout(() => {
      api.previewTransform(JSON.parse(body)).then(setPreview, (e) => setPreview({ ok: false, error: { step: null, message: String(e) } }));
    }, 350);
    return () => clearTimeout(timer);
  }, [body, input]);

  const inputCols = tables.data?.find((x) => x.full === input)?.columns ?? [];
  const colsAt = (i: number): ColInfo[] => preview?.step_columns?.[i] ?? (i === 0 ? inputCols : []);
  const setStep = (i: number, s: TransformStep) => setSteps((all) => all.map((x, k) => (k === i ? s : x)));
  const move = (i: number, d: number) => setSteps((all) => {
    const next = [...all];
    const [s] = next.splice(i, 1);
    next.splice(i + d, 0, s);
    return next;
  });

  async function save(andRun: boolean) {
    setBusy(andRun ? "run" : "save");
    setMsg(null);
    try {
      const b = { name: name.trim(), input_table: input, steps, output_table: outName };
      let saved = t;
      if (dirty) saved = t ? await api.saveTransform(t.id, b) : await api.createTransform(b);
      if (andRun && saved) {
        const r = await api.runTransform(saved.id);
        setMsg({ ok: true, text: `Wrote ${num(r.rows)} rows to ${r.table}. The raw data wasn't changed.` });
      } else {
        setMsg({ ok: true, text: "Saved." });
      }
      if (saved) onSaved(saved);
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(null);
    }
  }

  const errStep = preview && !preview.ok ? preview.error?.step ?? null : null;
  const grouped = useMemo(() => {
    const g: Record<string, TableInfo[]> = {};
    for (const x of tables.data ?? []) (g[x.schema] ??= []).push(x);
    return g;
  }, [tables.data]);

  return (
    <section className="panel detail transform-editor">
      {onBack && <button className="btn btn-link back" onClick={onBack}>← All transforms</button>}
      <div className="detail-head">
        <div className="grow">
          <input className="text-input title-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this transform, e.g. Clean billing customers" autoFocus={!t} />
          {t && (
            <p className="muted small">
              {t.last_error ? <span className="error-text">Last run failed: {t.last_error}</span>
                : t.last_run_at ? <>Last run {ago(t.last_run_at)}: {num(t.last_rows ?? 0)} rows in <code>{t.output_full}</code></>
                : "Saved, not run yet."}
            </p>
          )}
        </div>
        <div className="row-gap">
          <button className="btn" disabled={!!busy || !name.trim() || !input || errStep !== null || preview?.ok === false} onClick={() => save(true)}>
            {busy === "run" ? "Running…" : dirty ? "Save and run" : "Run now"}
          </button>
          <button className="btn btn-secondary" disabled={!!busy || !name.trim() || !input || !dirty} onClick={() => save(false)}>
            {busy === "save" ? "Saving…" : "Save"}
          </button>
          {onCancel && <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>}
        </div>
      </div>
      {msg && <p className={msg.ok ? "ok-note" : "error"}>{msg.text}</p>}

      {t && (
        <div className="tabs">
          <button className={tab === "build" ? "active" : ""} onClick={() => setTab("build")}>Steps and preview</button>
          <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>What happened</button>
        </div>
      )}
      {tab === "activity" && t ? <ActivityFeed transformId={t.id} compact /> : (
        <>
          <div className="t-step t-io">
            <span className="step-n">▶</span>
            <div>
              <h3>Start from</h3>
              <select className="text-input" value={input} onChange={(e) => setInput(e.target.value)}>
                <option value="">Pick a table…</option>
                {Object.entries(grouped).map(([schema, ts]) => (
                  <optgroup key={schema} label={schema === "raw" ? "raw: as it arrived" : "clean: made by transforms"}>
                    {ts.filter((x) => !(t && x.full === t.output_full)).map((x) => (
                      <option key={x.full} value={x.full}>{x.full} ({x.columns.length} columns{x.made_by ? `, from “${x.made_by.name}”` : ""})</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
          </div>

          {steps.map((s, i) => (
            <div key={i} className={`t-step ${errStep === i ? "bad" : ""} ${s.disabled ? "off" : ""}`}>
              <span className="step-n">{i + 1}</span>
              <div className="grow">
                <div className="t-step-head">
                  <h3>{label(s.op)}</h3>
                  <div className="t-step-tools">
                    <label className="small muted" title="Turn this step off without deleting it">
                      <input type="checkbox" checked={!s.disabled} onChange={(e) => setStep(i, { ...s, disabled: !e.target.checked })} /> on
                    </label>
                    <button className="btn btn-link" disabled={i === 0} onClick={() => move(i, -1)} title="Move up">↑</button>
                    <button className="btn btn-link" disabled={i === steps.length - 1} onClick={() => move(i, 1)} title="Move down">↓</button>
                    <button className="btn btn-link danger-text" onClick={() => setSteps((all) => all.filter((_, k) => k !== i))} title="Remove step">✕</button>
                  </div>
                </div>
                <StepFields step={s} cols={colsAt(i)} tables={tables.data ?? []} onChange={(x) => setStep(i, x)} />
                {errStep === i && <p className="error small">{preview?.error?.message}</p>}
              </div>
            </div>
          ))}

          <div className="t-step t-add">
            <span className="step-n">+</span>
            <div>
              <select className="text-input" value="" disabled={!input}
                onChange={(e) => e.target.value && setSteps((all) => [...all, newStep(e.target.value as StepOp, colsAt(all.length))])}>
                <option value="">{input ? "Add a step…" : "Pick a table to start from first"}</option>
                {OPS.map((o) => <option key={o.op} value={o.op}>{o.label}: {o.hint}</option>)}
              </select>
            </div>
          </div>

          <div className="t-step t-io">
            <span className="step-n">■</span>
            <div>
              <h3>Write to</h3>
              <div className="storage-pick">
                <code>clean.</code>
                <input className="text-input" value={output} onChange={(e) => setOutput(e.target.value)} placeholder={outName || "table_name"} />
              </div>
              <p className="muted small">Each run rebuilds this table from scratch.</p>
            </div>
          </div>

          <div className="t-preview">
            <div className="t-preview-head">
              <h3>Preview{preview?.ok ? <span className="muted small"> · {num(preview.row_count ?? 0)} rows{(preview.row_count ?? 0) > 50 ? ", first 50 shown" : ""}</span> : null}</h3>
              {preview?.sql && <button className="btn btn-link" onClick={() => setShowSql((v) => !v)}>{showSql ? "Hide the SQL" : "Show the SQL"}</button>}
            </div>
            {!input ? <p className="muted small">Pick a table to start from, then add steps. The result shows here as you go.</p>
              : !preview ? <p className="muted small">Working…</p>
              : !preview.ok && errStep === null ? <p className="error small">{preview.error?.message}</p>
              : !preview.ok ? <p className="muted small">Fix step {(errStep ?? 0) + 1} to see the result.</p>
              : <Grid cols={preview.columns ?? []} rows={preview.rows ?? []} />}
            {showSql && preview?.sql && <pre className="sql">{preview.sql}</pre>}
          </div>
        </>
      )}

      {t && (
        <div className="danger-zone">
          {confirmDelete ? (
            <p>
              Delete this transform?{" "}
              <button className="btn btn-danger" onClick={() => api.deleteTransform(t.id, false).then(onDeleted, (e) => setMsg({ ok: false, text: String(e) }))}>Delete, keep {t.output_full}</button>{" "}
              <button className="btn btn-danger" onClick={() => api.deleteTransform(t.id, true).then(onDeleted, (e) => setMsg({ ok: false, text: String(e) }))}>Delete it and the table</button>{" "}
              <button className="btn btn-secondary" onClick={() => setConfirmDelete(false)}>Keep it</button>
            </p>
          ) : (
            <button className="btn btn-link" onClick={() => setConfirmDelete(true)}>Delete transform…</button>
          )}
        </div>
      )}
    </section>
  );
}

function Grid({ cols, rows }: { cols: ColInfo[]; rows: unknown[][] }) {
  if (!rows.length) return <p className="muted small">No rows.</p>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr>{cols.map((c) => <th key={c.name} title={c.type}>{c.name}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((v, k) => <td key={k} className={v === null ? "muted" : ""}>{v === null ? "null" : String(v)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------ one step's fields */

function ColSelect({ cols, value, onChange, empty = "Pick a column…" }: { cols: ColInfo[]; value: string; onChange: (v: string) => void; empty?: string }) {
  return (
    <select className="text-input" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{empty}</option>
      {cols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
      {value && !cols.some((c) => c.name === value) && <option value={value}>{value} (not here)</option>}
    </select>
  );
}

function ColChips({ cols, value, onChange, ordered = false }: { cols: ColInfo[]; value: string[]; onChange: (v: string[]) => void; ordered?: boolean }) {
  return (
    <div className="pick-chips">
      {cols.map((c) => {
        const on = value.includes(c.name);
        return (
          <button key={c.name} type="button" className={`pick-chip ${on ? "on" : ""}`}
            onClick={() => onChange(on ? value.filter((x) => x !== c.name) : [...value, c.name])}>
            {ordered && on && value.length > 1 ? `${value.indexOf(c.name) + 1}. ` : ""}{c.name}
          </button>
        );
      })}
    </div>
  );
}

/** Comma-separated names, kept as typed while editing. */
function NamesInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  const [txt, setTxt] = useState(value.join(", "));
  return <input className="text-input" value={txt} placeholder={placeholder}
    onChange={(e) => { setTxt(e.target.value); onChange(e.target.value.split(",").map((x) => x.trim()).filter(Boolean)); }} />;
}

function StepFields({ step: s, cols, tables, onChange }: {
  step: TransformStep; cols: ColInfo[]; tables: TableInfo[]; onChange: (s: TransformStep) => void;
}) {
  const set = (patch: Record<string, unknown>) => onChange({ ...s, ...patch });
  const textCols = cols.filter((c) => TEXTY.has(c.type));

  switch (s.op) {
    case "split":
      return (
        <div className="t-fields">
          <label>Column <ColSelect cols={cols} value={s.column} onChange={(v) => set({ column: v })} /></label>
          <label>Split at <input className="text-input narrow" value={s.separator} maxLength={5} onChange={(e) => set({ separator: e.target.value })} /></label>
          <label className="wide">Into columns named <NamesInput value={s.into ?? []} onChange={(v) => set({ into: v })} placeholder="e.g. prefix, number, region" /></label>
          <label className="check"><input type="checkbox" checked={!!s.keep_original} onChange={(e) => set({ keep_original: e.target.checked })} /> keep the original column too</label>
        </div>
      );
    case "parse_name":
      return (
        <div className="t-fields">
          <label>Column with full names <ColSelect cols={cols} value={s.column} onChange={(v) => set({ column: v })} /></label>
          <label>First name column <input className="text-input" value={s.first} onChange={(e) => set({ first: e.target.value })} /></label>
          <label>Last name column <input className="text-input" value={s.last} onChange={(e) => set({ last: e.target.value })} /></label>
          <label className="check"><input type="checkbox" checked={!!s.keep_original} onChange={(e) => set({ keep_original: e.target.checked })} /> keep the original column too</label>
          <p className="muted small wide">“Smith, Jane” and “Jane Smith” both become Jane · Smith. Extra spaces are removed. A single word goes in the last name.</p>
        </div>
      );
    case "join":
      return (
        <div className="t-fields">
          <div className="wide"><span className="small muted">Columns, in the order you click them</span><ColChips ordered cols={cols} value={s.columns ?? []} onChange={(v) => set({ columns: v })} /></div>
          <label>With <input className="text-input narrow" value={s.separator ?? " "} onChange={(e) => set({ separator: e.target.value })} /> between</label>
          <label>Into a column named <input className="text-input" value={s.into} onChange={(e) => set({ into: e.target.value })} placeholder="e.g. full_name" /></label>
          <label className="check"><input type="checkbox" checked={s.keep_originals !== false} onChange={(e) => set({ keep_originals: e.target.checked })} /> keep the original columns too</label>
        </div>
      );
    case "clean":
      return (
        <div className="t-fields">
          <div className="wide"><span className="small muted">Text columns to clean (none picked = all of them)</span><ColChips cols={textCols} value={s.columns ?? []} onChange={(v) => set({ columns: v })} /></div>
          <label className="check"><input type="checkbox" checked={s.trim !== false} onChange={(e) => set({ trim: e.target.checked })} /> trim spaces at the ends and squeeze double spaces</label>
          <label>Capitals
            <select className="text-input" value={s.case ?? "none"} onChange={(e) => set({ case: e.target.value })}>
              <option value="none">leave as they are</option>
              <option value="title">Title Case</option>
              <option value="upper">UPPER CASE</option>
              <option value="lower">lower case</option>
            </select>
          </label>
        </div>
      );
    case "rename":
      return (
        <div className="t-fields rename-grid">
          {cols.map((c) => (
            <label key={c.name}><code>{c.name}</code> →
              <input className="text-input" value={s.renames?.[c.name] ?? ""} placeholder="keep the name"
                onChange={(e) => set({ renames: { ...(s.renames ?? {}), [c.name]: e.target.value } })} />
            </label>
          ))}
        </div>
      );
    case "drop":
      return (
        <div className="t-fields">
          <div className="wide"><span className="small muted">Columns to leave out</span><ColChips cols={cols} value={s.columns ?? []} onChange={(v) => set({ columns: v })} /></div>
        </div>
      );
    case "stack": {
      const other = tables.find((x) => x.full === s.table);
      const theirs = other?.columns ?? [];
      return (
        <div className="t-fields">
          <label className="wide">Add the rows of
            <select className="text-input" value={s.table} onChange={(e) => set({ table: e.target.value, mapping: {} })}>
              <option value="">Pick a table…</option>
              {tables.map((x) => <option key={x.full} value={x.full}>{x.full}</option>)}
            </select>
          </label>
          {other && (
            <div className="wide map-grid">
              <span className="small muted">Our column</span><span className="small muted">comes from their column</span>
              {cols.map((c) => {
                const auto = theirs.some((x) => x.name === c.name) ? c.name : "";
                const v = s.mapping?.[c.name] ?? auto;
                return (
                  <span key={c.name} className="map-row">
                    <code>{c.name}</code>
                    <ColSelect cols={theirs} value={v} empty="(leave empty)" onChange={(x) => set({ mapping: { ...(s.mapping ?? {}), [c.name]: x } })} />
                  </span>
                );
              })}
            </div>
          )}
          <label className="check wide">
            <input type="checkbox" checked={!!s.label_column} onChange={(e) => set({ label_column: e.target.checked ? "came_from" : "" })} />
            add a column saying where each row came from
          </label>
          {!!s.label_column && (
            <>
              <label>Column name <input className="text-input" value={s.label_column} onChange={(e) => set({ label_column: e.target.value })} /></label>
              <label>Our rows say <input className="text-input" value={s.this_label} onChange={(e) => set({ this_label: e.target.value })} placeholder="e.g. billing" /></label>
              <label>Their rows say <input className="text-input" value={s.other_label} onChange={(e) => set({ other_label: e.target.value })} placeholder={s.table || "e.g. sales"} /></label>
            </>
          )}
        </div>
      );
    }
    case "dedupe":
      return (
        <div className="t-fields">
          <div className="wide"><span className="small muted">Two rows are the same when these match</span><ColChips cols={cols} value={s.columns ?? []} onChange={(v) => set({ columns: v })} /></div>
          <label className="check"><input type="checkbox" checked={s.ignore_case !== false} onChange={(e) => set({ ignore_case: e.target.checked })} /> ignore capitals and extra spaces when comparing</label>
          <p className="muted small wide">One row is kept from each group of matches.</p>
        </div>
      );
  }
}
