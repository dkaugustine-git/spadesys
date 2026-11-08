import { useState } from "react";
import { api, type FileAnalysis, type Source } from "../api";
import { cell, num } from "../format";

interface Props {
  analysis: FileAnalysis;
  onDone: (source: Source) => void;
  onLater: () => void;
}

/** Ask the user what to do with a file that's sitting in storage. */
export function LoadDialog({ analysis: a, onDone, onLater }: Props) {
  const recommended = a.suggestions.find((s) => s.recommended);
  const [choice, setChoice] = useState<string>(recommended ? recommended.source_id : "new");
  const [newName, setNewName] = useState(a.suggested_new_name);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setErr(null);
    try {
      const body = choice === "new" ? { key: a.key, new_name: newName } : { key: a.key, source_id: choice };
      onDone(await api.loadStaged(body));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onLater()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="load-title">
        <h2 id="load-title">What should we do with <code>{a.filename}</code>?</h2>
        <p className="muted">
          It's saved in storage ({num(a.row_count)} rows, {a.columns.length} columns). Nothing else has happened yet.
        </p>

        <div className="table-wrap peek">
          <table className="data">
            <thead><tr>{a.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {a.preview_rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{cell(v)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
        <p className="muted small">First {a.preview_rows.length} rows</p>

        <fieldset className="choices">
          {a.suggestions.map((s) => (
            <label key={s.source_id} className={`choice ${choice === s.source_id ? "on" : ""}`}>
              <input type="radio" name="target" checked={choice === s.source_id} onChange={() => setChoice(s.source_id)} />
              <div>
                <div className="choice-title">
                  Add to the existing table “{s.source_name}”
                  {s.recommended && <span className="tag">recommended</span>}
                </div>
                <div className="muted small"><code>raw.{s.table_name}</code> · already has {num(s.row_count)} rows</div>
                <ul className="reasons">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              </div>
            </label>
          ))}

          <label className={`choice ${choice === "new" ? "on" : ""}`}>
            <input type="radio" name="target" checked={choice === "new"} onChange={() => setChoice("new")} />
            <div style={{ flex: 1 }}>
              <div className="choice-title">Create a new table</div>
              {choice === "new" && (
                <input
                  className="text-input"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Name"
                  aria-label="Name for the new table"
                />
              )}
              <div className="muted small">
                {a.suggestions.length === 0 ? "Nothing existing looks like this file." : "Keeps it separate from the tables above."}
              </div>
            </div>
          </label>
        </fieldset>

        {err && <p className="error">{err}</p>}

        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={onLater} disabled={busy}>Decide later (keep in storage)</button>
          <button className="btn" onClick={go} disabled={busy || (choice === "new" && !newName.trim())}>
            {busy ? "Starting…" : choice === "new" ? "Create table and load" : "Add to table"}
          </button>
        </div>
      </div>
    </div>
  );
}
