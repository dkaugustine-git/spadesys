import { useEffect, useRef, useState } from "react";
import { api, type ExtractDetail, type Layout } from "../../api";
import { LayoutPicker } from "../LayoutPicker";

/** The extract's saved file layout, in words, with a way to set it up from a sample file. */
export function FileLayout({ x, onSaved }: { x: ExtractDetail; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [samples, setSamples] = useState<{ ref: string; label: string }[] | null>(null);
  const [ref, setRef] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    api.extractSamples(x.id).then((s) => { setSamples(s); if (!ref && s[0]) setRef(s[0].ref); }, (e) => setErr(String(e)));
  }, [open, x.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function close() { setOpen(false); setFile(null); setLayout(null); setErr(null); }

  async function save(reset: boolean) {
    setBusy(true);
    setErr(null);
    try {
      await api.updateExtract(x.id, reset ? { reset_layout: true } : { layout: layout! });
      close();
      onSaved();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  // Start from the saved layout (if any); otherwise let Spadesys guess from the sample.
  const startFrom = layout ?? x.layout ?? null;
  const sourceKey = file ? `file:${file.name}:${file.size}` : `ref:${ref}`;

  return (
    <div className={`file-layout ${open ? "open" : ""}`}>
      <div className="fl-head">
        <span>📄 <b>File layout:</b> {x.layout_text}{!x.layout && <span className="muted"> (the standard way)</span>}</span>
        {!open && <button className="btn btn-link" onClick={() => setOpen(true)}>{x.layout ? "Change…" : "Set up from a sample file…"}</button>}
      </div>
      {open && (
        <>
          <p className="muted small">
            Pick a file shaped like the ones this extract gets. Say where the table is once, and every future file is read the same way.
          </p>
          <div className="row-gap fl-pick">
            {!!samples?.length && (
              <select className="text-input" value={file ? "" : ref} onChange={(e) => { setFile(null); setRef(e.target.value); setLayout(null); }}>
                {file && <option value="">{file.name} (from your computer)</option>}
                {samples.map((s) => <option key={s.ref} value={s.ref}>{s.label}</option>)}
              </select>
            )}
            <button className="btn btn-secondary" onClick={() => fileInput.current?.click()}>Use a file from my computer…</button>
            <input ref={fileInput} type="file" hidden accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods"
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) { setFile(f); setLayout(null); } }} />
          </div>
          {samples && !samples.length && !file && <p className="muted small">No files here yet. Use one from your computer (it won't be loaded).</p>}
          {(file || ref) && (
            <LayoutPicker key={sourceKey} value={startFrom} onChange={setLayout}
              load={(l) => (file ? api.previewFileLayout(file, l) : api.extractLayoutPreview(x.id, ref, l))} />
          )}
          {err && <p className="error">{err}</p>}
          <div className="row-gap">
            <button className="btn" disabled={busy || !layout} onClick={() => save(false)}>Save this layout</button>
            {x.layout && <button className="btn btn-secondary" disabled={busy} onClick={() => save(true)}>Go back to the standard way</button>}
            <button className="btn btn-secondary" onClick={close}>Cancel</button>
          </div>
        </>
      )}
    </div>
  );
}

/** For a new extract: optionally set the layout from a file on your computer before it exists. */
export function SampleLayout({ value, onChange }: { value: Layout | null; onChange: (l: Layout | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  return (
    <>
      <p className="muted small">
        If the files have titles or notes above the table, or a totals row under it, pick one now and show Spadesys where the table is.
        Plain files with headers on row 1 don't need this.
      </p>
      <div className="row-gap">
        <button className="btn btn-secondary" onClick={() => fileInput.current?.click()}>{file ? "Pick a different file…" : "Pick a sample file…"}</button>
        {file && <button className="btn btn-link" onClick={() => { setFile(null); onChange(null); }}>Don't use a layout</button>}
        <input ref={fileInput} type="file" hidden accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods"
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) { setFile(f); onChange(null); } }} />
      </div>
      {file && (
        <LayoutPicker key={`${file.name}:${file.size}`} value={value} onChange={onChange} load={(l) => api.previewFileLayout(file, l)} />
      )}
    </>
  );
}
