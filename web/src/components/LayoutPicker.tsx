import { useEffect, useRef, useState } from "react";
import type { Layout, LayoutPreview } from "../api";
import { num } from "../format";

const same = (a: Layout | null | undefined, b: Layout | null | undefined) =>
  !!a && !!b && a.header_row === b.header_row && a.data_row === b.data_row && a.stop === b.stop
  && (a.stop !== "text" || (a.stop_text ?? "") === (b.stop_text ?? "")) && (a.sheet ?? null) === (b.sheet ?? null);

const width = (r: string[]) => r.filter((c) => c !== "").length;
const first = (r: string[]) => r.find((c) => c !== "") ?? "";

/** Which row (1-based) the layout stops at, within the rows we can see. */
function stopRow(grid: string[][], l: Layout): number | null {
  for (let n = l.data_row; n <= grid.length; n++) {
    const r = grid[n - 1];
    if (l.stop === "blank" && width(r) === 0) return n;
    if (l.stop === "text" && l.stop_text && first(r).toLowerCase().startsWith(l.stop_text.trim().toLowerCase())) return n;
  }
  return null;
}

/**
 * Show a file as raw numbered rows and let the user say where the table is:
 * which sheet, the header row, the first data row, and where to stop.
 * `load` fetches a preview for a layout (null = let Spadesys guess).
 */
export function LayoutPicker({ load, value, onChange }: {
  load: (layout: Layout | null) => Promise<LayoutPreview>;
  value: Layout | null;
  onChange: (l: Layout) => void;
}) {
  const [p, setP] = useState<LayoutPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"header" | "data">("header");
  const loadRef = useRef(load);
  loadRef.current = load;

  const key = JSON.stringify(value);
  useEffect(() => {
    let gone = false;
    const t = setTimeout(() => {
      loadRef.current(value).then((res) => {
        if (gone) return;
        setP(res);
        setErr(null);
        if (!value) onChange(res.layout); // start from Spadesys's guess
      }, (e) => !gone && setErr(String(e)));
    }, value ? 200 : 0);
    return () => { gone = true; clearTimeout(t); };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <p className="error">{err}</p>;
  if (!p) return <p className="muted small">Reading the file…</p>;
  const l: Layout = value ?? p.layout;
  const set = (patch: Partial<Layout>) => onChange({ ...l, ...patch });
  const stop = stopRow(p.grid, l);
  const cols = Math.max(1, ...p.grid.map((r) => r.length));

  function pick(n: number) {
    if (mode === "header") {
      set({ header_row: n, data_row: l.data_row > n ? l.data_row : n + 1 });
      setMode("data");
    } else {
      set({ data_row: n, header_row: l.header_row >= n ? 0 : l.header_row });
    }
  }

  const rowClass = (n: number) =>
    n === l.header_row ? "lp-header"
      : n < l.data_row ? "lp-skip"
      : stop !== null && n >= stop ? (n === stop ? "lp-stop" : "lp-skip")
      : width(p.grid[n - 1]) === 0 ? "lp-blank" : "lp-data";

  return (
    <div className="layout-picker">
      <div className="lp-controls">
        {p.sheets.length > 1 && (
          <label>Sheet
            <select className="text-input" value={l.sheet ?? p.sheet ?? ""} onChange={(e) => onChange({ ...l, sheet: e.target.value })}>
              {p.sheets.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
        )}
        <label>Column headers on row
          <input className="text-input narrow" type="number" min={0} value={l.header_row}
            onChange={(e) => set({ header_row: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>Data starts on row
          <input className="text-input narrow" type="number" min={1} value={l.data_row}
            onChange={(e) => set({ data_row: Math.max(1, Number(e.target.value) || 1) })} />
        </label>
        <label>Stop at
          <select className="text-input" value={l.stop} onChange={(e) => set({ stop: e.target.value as Layout["stop"] })}>
            <option value="end">the end of the file</option>
            <option value="blank">the first blank row</option>
            <option value="text">a row starting with…</option>
          </select>
        </label>
        {l.stop === "text" && (
          <label>Text
            <input className="text-input" value={l.stop_text ?? ""} placeholder="Total" onChange={(e) => set({ stop_text: e.target.value })} />
          </label>
        )}
      </div>

      <div className="lp-help">
        <span className="muted small">Click a row to set the</span>
        <span className="seg">
          <button type="button" className={mode === "header" ? "on" : ""} onClick={() => setMode("header")}>header row</button>
          <button type="button" className={mode === "data" ? "on" : ""} onClick={() => setMode("data")}>first data row</button>
        </span>
        <label className="small"><input type="checkbox" checked={l.header_row === 0}
          onChange={(e) => set(e.target.checked ? { header_row: 0 } : { header_row: Math.max(1, l.data_row - 1), data_row: Math.max(2, l.data_row) })} /> no header row</label>
        {!same(l, p.guess) && (
          <button type="button" className="btn btn-link small" onClick={() => onChange(p.guess)}>use Spadesys's guess</button>
        )}
      </div>

      <div className="table-wrap lp-grid">
        <table>
          <tbody>
            {p.grid.map((r, i) => {
              const n = i + 1;
              const c = rowClass(n);
              return (
                <tr key={n} className={c} onClick={() => pick(n)} title={`Row ${n}: click to make it the ${mode === "header" ? "header row" : "first data row"}`}>
                  <th className="lp-n">{n}</th>
                  <td className="lp-tag">{c === "lp-header" ? "headers" : c === "lp-stop" ? "stop" : n === l.data_row ? "data →" : ""}</td>
                  {Array.from({ length: cols }, (_, k) => <td key={k}>{r[k] ?? ""}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {p.total_rows > p.grid.length && <p className="muted small">Showing the first {p.grid.length} of {num(p.total_rows)} rows.</p>}

      {p.ok ? (
        <div className="lp-result">
          <p className="small">
            <b>Loads as {num(p.row_count ?? 0)} rows × {p.columns?.length ?? 0} columns:</b>{" "}
            {p.columns?.map((c) => <code key={c} className="lp-col">{c}</code>)}
          </p>
          {!!p.notes?.length && <ul className="plain small muted">{p.notes.map((x) => <li key={x}>{x}</li>)}</ul>}
        </div>
      ) : (
        <p className="error small">{p.error}</p>
      )}
    </div>
  );
}
