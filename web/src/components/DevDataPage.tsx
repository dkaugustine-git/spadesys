import { useEffect, useMemo, useState } from "react";
import { api, type Catalog, type DbConnection, type DbConnectionIn, type FieldSpec, type Preview } from "../api";
import { cell, num } from "../format";

const DEFAULT_FOR_TYPE: Record<string, string> = {
  text: "word", integer: "integer_range", decimal: "decimal_range", boolean: "boolean",
  date: "date_past", timestamp: "timestamp_recent", uuid: "uuid",
};

interface Target { connection: DbConnection; schema: string; table: string }

export function DevDataPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [mode, setMode] = useState<"db" | "paste">("db");
  const [fields, setFields] = useState<FieldSpec[]>([]);
  const [target, setTarget] = useState<Target | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.catalog().then(setCatalog, (e) => setErr(String(e))); }, []);

  return (
    <main className="layout devdata">
      <section className="panel">
        <h2>Dev data</h2>
        <p className="muted small">Make realistic fake rows for a table. Start from one of these:</p>
        <nav className="tabs" role="tablist">
          <button className={mode === "db" ? "active" : ""} onClick={() => setMode("db")}>A database table</button>
          <button className={mode === "paste" ? "active" : ""} onClick={() => setMode("paste")}>Paste column names</button>
        </nav>
        {mode === "db" ? (
          <DbPicker
            onPicked={(t, f) => { setTarget(t); setFields(f); setErr(null); }}
            onError={setErr}
          />
        ) : (
          <PasteBox onFields={(f) => { setTarget(null); setFields(f); setErr(null); }} onError={setErr} />
        )}
        {err && <p className="error">{err}</p>}
      </section>

      <section className="panel">
        {!fields.length || !catalog ? (
          <div className="muted">
            <h2>Columns</h2>
            <p>Pick a table or paste column names. Each column gets a suggested type and kind of fake value, with the reason. Change anything you disagree with.</p>
          </div>
        ) : (
          <Designer key={target ? `${target.connection.id}.${target.schema}.${target.table}` : fields.map((f) => f.name).join()}
            catalog={catalog} fields={fields} setFields={setFields} target={target} />
        )}
      </section>
    </main>
  );
}

/* --------------------------------------------------------- source: database */

function DbPicker({ onPicked, onError }: { onPicked: (t: Target, f: FieldSpec[]) => void; onError: (e: string | null) => void }) {
  const [conns, setConns] = useState<DbConnection[] | null>(null);
  const [connId, setConnId] = useState<string>("");
  const [adding, setAdding] = useState(false);
  const [tree, setTree] = useState<{ schema: string; tables: string[] }[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const reload = () => api.connections().then((c) => {
    setConns(c);
    if (!c.length) setAdding(true);
    else if (!c.find((x) => x.id === connId)) setConnId(c[0].id);
  }, (e) => onError(String(e)));
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  useEffect(() => {
    setTree(null);
    if (!connId) return;
    setLoading(true);
    api.tables(connId).then(setTree, (e) => onError(String(e))).finally(() => setLoading(false));
  }, [connId, onError]);

  const conn = conns?.find((c) => c.id === connId);

  async function pick(schema: string, table: string) {
    if (!conn) return;
    setPicked(`${schema}.${table}`);
    onError(null);
    try {
      onPicked({ connection: conn, schema, table }, await api.describeTable(conn.id, schema, table));
    } catch (e) {
      onError(String(e));
    }
  }

  if (adding) {
    return <ConnectionForm onCancel={conns?.length ? () => setAdding(false) : undefined}
      onSaved={(c) => { setAdding(false); setConnId(c.id); reload(); }} />;
  }

  return (
    <div>
      <div className="row">
        <select value={connId} onChange={(e) => setConnId(e.target.value)} aria-label="Database connection" style={{ flex: 1, minWidth: 0 }}>
          {conns?.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.kind} · {c.host}:{c.port}/{c.database}</option>)}
        </select>
        <button className="btn btn-secondary" onClick={() => setAdding(true)}>+ Add</button>
      </div>
      {loading && <p className="muted pad">Looking at tables…</p>}
      {tree && (
        <div className="tree">
          {tree.map((s) => (
            <details key={s.schema} open={tree.length < 4}>
              <summary><code>{s.schema}</code> <span className="muted small">{s.tables.length} tables</span></summary>
              <ul>
                {s.tables.map((t) => (
                  <li key={t}>
                    <button className={`tree-item ${picked === `${s.schema}.${t}` ? "selected" : ""}`} onClick={() => pick(s.schema, t)}>{t}</button>
                  </li>
                ))}
                {!s.tables.length && <li className="muted small">no tables</li>}
              </ul>
            </details>
          ))}
        </div>
      )}
      {conn && (
        <button className="btn btn-link small" onClick={async () => {
          await api.deleteConnection(conn.id); setConnId(""); reload();
        }}>Remove this connection</button>
      )}
    </div>
  );
}

function ConnectionForm({ onSaved, onCancel }: { onSaved: (c: DbConnection) => void; onCancel?: () => void }) {
  const [c, setC] = useState<DbConnectionIn>({
    name: "My dev database", kind: "postgresql", host: "host.docker.internal", port: 5432, database: "", username: "", password: "",
  });
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof DbConnectionIn, v: string | number) => setC((x) => ({ ...x, [k]: v }));

  const isLocal = ["localhost", "127.0.0.1", "::1", "0.0.0.0"].includes(c.host.trim().toLowerCase());

  async function test() {
    setBusy(true);
    const r: { ok: boolean; version?: string; error?: string; hint?: string } =
      await api.testConnection(c).catch((e) => ({ ok: false, error: String(e) }));
    setStatus(r.ok
      ? { ok: true, text: `Connected ✓ ${r.version ? r.version.split(" on ")[0] : ""}` }
      : { ok: false, text: [r.error || "Failed", r.hint].filter(Boolean).join("\n\n") });
    setBusy(false);
  }
  async function save() {
    setBusy(true);
    try { onSaved(await api.saveConnection(c)); } catch (e) { setStatus({ ok: false, text: e instanceof Error ? e.message : String(e) }); setBusy(false); }
  }

  return (
    <div className="conn-form">
      <h3>Connect to a database</h3>
      <label>Name<input className="text-input" value={c.name} onChange={(e) => set("name", e.target.value)} /></label>
      <label>Type
        <select value={c.kind} onChange={(e) => { const k = e.target.value as DbConnectionIn["kind"]; setC((x) => ({ ...x, kind: k, port: k === "mysql" ? 3306 : 5432 })); }}>
          <option value="postgresql">PostgreSQL</option>
          <option value="mysql">MySQL</option>
        </select>
      </label>
      <div className="row">
        <label style={{ flex: 3 }}>Host<input className="text-input" value={c.host} onChange={(e) => set("host", e.target.value)} /></label>
        <label style={{ flex: 1 }}>Port<input className="text-input" type="number" value={c.port} onChange={(e) => set("port", Number(e.target.value))} /></label>
      </div>
      <p className="muted small hint">
        Spadesys runs inside Docker, so <code>localhost</code> means Spadesys itself. For a database on your computer use <code>host.docker.internal</code>. For Spadesys's own Postgres use host <code>postgres</code>, port 5432, user/password <code>spadesys</code>.
      </p>
      <label>Database<input className="text-input" value={c.database} onChange={(e) => set("database", e.target.value)} /></label>
      <div className="row">
        <label style={{ flex: 1 }}>User<input className="text-input" value={c.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" /></label>
        <label style={{ flex: 1 }}>Password<input className="text-input" type="password" value={c.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" /></label>
      </div>
      <p className="muted small">Saved in Spadesys's own database as typed. Use dev credentials, not production ones.</p>
      {status && <p className={status.ok ? "okmsg" : "error"} style={{ whiteSpace: "pre-line" }}>{status.text}</p>}
      {status && !status.ok && isLocal && (
        <button className="btn btn-secondary full" onClick={() => { set("host", "host.docker.internal"); setStatus(null); }}>
          Use host.docker.internal instead
        </button>
      )}
      <div className="row">
        <button className="btn btn-secondary" onClick={test} disabled={busy}>Test</button>
        <button className="btn" onClick={save} disabled={busy || !c.host || !c.username}>Save</button>
        {onCancel && <button className="btn btn-link" onClick={onCancel}>Cancel</button>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ source: paste */

function PasteBox({ onFields, onError }: { onFields: (f: FieldSpec[]) => void; onError: (e: string | null) => void }) {
  const [text, setText] = useState("");
  const suggest = (t: string) => api.recommend(t).then(onFields, (e) => onError(String(e)));
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  const exampleRows = lines.length > 1 && /[\t,;|]/.test(lines[0]) ? lines.length - 1 : 0;

  async function fromClipboard() {
    try {
      const t = await navigator.clipboard.readText();
      if (!t.trim()) return onError("The clipboard is empty. Copy the header row (and a few rows under it) first.");
      setText(t);
      onError(null);
      suggest(t);
    } catch {
      onError("The browser didn't allow reading the clipboard. Click in the box and press Ctrl+V instead.");
    }
  }

  return (
    <div>
      <p className="muted small">
        Copy the header row from a spreadsheet or table (add a few rows under it and the types get better), then paste.
      </p>
      <textarea className="text-input paste" rows={8} value={text} onChange={(e) => setText(e.target.value)}
        placeholder={"customer_id, first_name, email, zip, signup_date, is_active\n\n…or one per line, or a range copied from Excel / Google Sheets"} />
      {exampleRows > 0 && (
        <p className="muted small">First line is the column names; the {exampleRows} line{exampleRows === 1 ? "" : "s"} under it are used as examples.</p>
      )}
      <div className="row-gap">
        <button className="btn" onClick={fromClipboard}>Paste from clipboard</button>
        <button className="btn" disabled={!text.trim()} onClick={() => suggest(text)}>Suggest types</button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- designer */

function Designer({ catalog, fields, setFields, target }: {
  catalog: Catalog; fields: FieldSpec[]; setFields: (f: FieldSpec[]) => void; target: Target | null;
}) {
  const [rows, setRows] = useState(100);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmInsert, setConfirmInsert] = useState(false);

  const gens = useMemo(() => Object.fromEntries(catalog.generators.map((g) => [g.key, g])), [catalog]);
  const filename = `${target?.table ?? "dev_data"}.csv`;
  const body = { fields, rows, connection_id: target?.connection.id ?? null, filename };

  // Live preview, debounced.
  useEffect(() => {
    const t = setTimeout(() => {
      api.previewDevData({ ...body, rows: 10 }).then((p) => { setPreview(p); setPreviewErr(null); }, (e) => setPreviewErr(String(e)));
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fields, target]);

  const update = (i: number, patch: Partial<FieldSpec>) => setFields(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));

  function setType(i: number, type: string) {
    const f = fields[i];
    const g = gens[f.generator];
    if (g && g.types.includes(type)) return update(i, { type });
    const def = DEFAULT_FOR_TYPE[type];
    update(i, { type, generator: def, params: { ...gens[def].defaults } });
  }
  function setGen(i: number, key: string) {
    update(i, { generator: key, params: { ...gens[key].defaults, ...(key === "existing" ? { ref: fields[i].params.ref ?? "" } : {}) } });
  }

  async function run(label: string, fn: () => Promise<string>) {
    setBusy(label);
    setResult(null);
    try { setResult({ ok: true, text: await fn() }); } catch (e) { setResult({ ok: false, text: e instanceof Error ? e.message : String(e) }); }
    setBusy(null);
    setConfirmInsert(false);
  }

  const grouped = (type: string, current: string) => {
    const groups: Record<string, typeof catalog.generators> = {};
    for (const g of catalog.generators) if (g.types.includes(type) || g.key === current) (groups[g.group] ??= []).push(g);
    return groups;
  };

  return (
    <>
      <div className="panel-head">
        <div>
          <h2>Columns</h2>
          <p className="muted small">
            {target ? <>From <code>{target.schema}.{target.table}</code> on {target.connection.name}</> : "From pasted column names"} · {fields.length} columns
          </p>
        </div>
      </div>

      <div className="table-wrap">
        <table className="designer">
          <thead><tr><th>Column</th><th>Type</th><th>Fake values</th><th>Settings</th><th title="Percent of rows left empty">Empty %</th><th>Unique</th><th /></tr></thead>
          <tbody>
            {fields.map((f, i) => {
              const g = gens[f.generator];
              const paramKeys = Object.keys(g?.defaults ?? {});
              return [
                <tr key={`${i}a`} className="field-row">
                  <td>
                    <input className="text-input slim" value={f.name} onChange={(e) => update(i, { name: e.target.value })} aria-label="Column name" />
                    {f.db_type && <div className="muted small">db: <code>{f.db_type}</code></div>}
                  </td>
                  <td>
                    <select value={f.type} onChange={(e) => setType(i, e.target.value)} aria-label={`Type of ${f.name}`}>
                      {catalog.types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                    </select>
                  </td>
                  <td>
                    <select value={f.generator} onChange={(e) => setGen(i, e.target.value)} aria-label={`Fake values for ${f.name}`}>
                      {Object.entries(grouped(f.type, f.generator)).map(([grp, list]) => (
                        <optgroup key={grp} label={grp}>{list.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</optgroup>
                      ))}
                    </select>
                  </td>
                  <td className="params">
                    {paramKeys.map((k) => (
                      <label key={k} className="param">
                        <span>{k.replace(/_/g, " ")}</span>
                        <input className="text-input slim" value={String(f.params[k] ?? "")}
                          onChange={(e) => update(i, { params: { ...f.params, [k]: e.target.value } })}
                          placeholder={k === "ref" ? "schema.table.column" : ""} />
                      </label>
                    ))}
                  </td>
                  <td><input className="text-input slim num-in" type="number" min={0} max={100} value={f.null_percent}
                    onChange={(e) => update(i, { null_percent: Math.max(0, Math.min(100, Number(e.target.value))) })} aria-label="Empty percent" /></td>
                  <td><input type="checkbox" checked={f.unique} onChange={(e) => update(i, { unique: e.target.checked })} aria-label="Unique" /></td>
                  <td><button className="btn btn-ghost" title="Remove column" onClick={() => setFields(fields.filter((_, j) => j !== i))}>×</button></td>
                </tr>,
                (f.reason || f.warning) && (
                  <tr key={`${i}b`} className="reason-row">
                    <td colSpan={7}>
                      {f.warning ? <span className="warn-inline">⚠ {f.warning}</span> : <span className="muted small">💡 {f.reason}</span>}
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
      <button className="btn btn-link" onClick={() => setFields([...fields, {
        name: `column_${fields.length + 1}`, type: "text", generator: "word", params: {}, null_percent: 0, unique: false,
        max_length: null, db_type: null, nullable: true, reason: null, warning: null,
      }])}>+ Add column</button>

      <h3 className="section-title">Preview <span className="muted small">(10 sample rows, refreshes as you edit)</span></h3>
      {previewErr && <p className="error">{previewErr}</p>}
      {preview && !previewErr && (
        <div className="table-wrap peek">
          <table className="data">
            <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{preview.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v === null ? <span className="null">null</span> : cell(v)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}

      <div className="make">
        <label className="row-count">How many rows?
          <input className="text-input slim" type="number" min={1} max={100000} value={rows} onChange={(e) => setRows(Math.max(1, Math.min(100000, Number(e.target.value))))} />
        </label>
        <div className="actions">
          <button className="btn btn-secondary" disabled={!!busy} onClick={() => run("download", async () => {
            await api.downloadDevData(body); return `Downloaded ${num(rows)} rows as ${filename}.`;
          })}>Download CSV</button>
          <button className="btn btn-secondary" disabled={!!busy} onClick={() => run("storage", async () => {
            const r = await api.devDataToStorage(body); return `Saved ${num(rows)} rows to storage at ${r.key}. Find it on the Storage page.`;
          })}>Save to storage</button>
          {target && !confirmInsert && (
            <button className="btn" disabled={!!busy} onClick={() => setConfirmInsert(true)}>Insert into {target.table}…</button>
          )}
        </div>
      </div>
      {target && confirmInsert && (
        <div className="confirm-box">
          <p>This adds <b>{num(rows)} rows</b> to <code>{target.schema}.{target.table}</code> on <b>{target.connection.name}</b> ({target.connection.host}). If any row is refused, nothing is added.</p>
          <div className="row">
            <button className="btn" disabled={!!busy} onClick={() => run("insert", async () => {
              const r = await api.insertDevData({ ...body, connection_id: target.connection.id, schema_name: target.schema, table: target.table });
              return `Inserted ${num(r.inserted)} rows into ${target.schema}.${target.table}.`;
            })}>{busy === "insert" ? "Inserting…" : "Yes, insert"}</button>
            <button className="btn btn-link" onClick={() => setConfirmInsert(false)}>Cancel</button>
          </div>
        </div>
      )}
      {busy && busy !== "insert" && <p className="muted">Working…</p>}
      {result && <p className={result.ok ? "okmsg" : "error"}>{result.text}</p>}
    </>
  );
}
