import { useCallback, useEffect, useRef, useState } from "react";
import { api, type StorageFolder, type StoragePreview } from "../api";
import { ago, human } from "../format";

interface Props {
  onLoadFile: (key: string) => void;
  onMakePipeline?: (bucket: string, prefix: string) => void;
}

type Confirm =
  | { kind: "file"; key: string }
  | { kind: "folder"; prefix: string; files: number; size: number };

/** Browse what's in object storage (MinIO) like a file explorer: folders, upload, download, delete. */
export function StoragePage({ onLoadFile, onMakePipeline }: Props) {
  const [buckets, setBuckets] = useState<string[]>([]);
  const [bucket, setBucket] = useState<string | null>(null);
  const [prefix, setPrefix] = useState("");
  const [folder, setFolder] = useState<StorageFolder | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<StoragePreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [newFolder, setNewFolder] = useState<string | null>(null); // null = not typing a name
  const [busy, setBusy] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.buckets().then((b) => {
      setBuckets(b.buckets);
      setBucket(b.default);
    }, (e) => setErr(String(e)));
  }, []);

  const reload = useCallback(() => {
    if (!bucket) return;
    api.listFolder(bucket, prefix).then(setFolder, (e) => setErr(String(e)));
  }, [bucket, prefix]);

  useEffect(() => {
    setFolder(null);
    setConfirm(null);
    setNewFolder(null);
    reload();
  }, [reload]);

  useEffect(() => {
    setPreview(null);
    if (bucket && selected) api.previewObject(bucket, selected).then(setPreview, (e) => setErr(String(e)));
  }, [bucket, selected]);

  const open = (p: string) => { setPrefix(p); setSelected(null); setNote(null); setErr(null); };
  const parts = prefix.split("/").filter(Boolean);
  const isCsv = (k: string) => /\.(csv|tsv|txt|xlsx|xlsm|xls|ods)$/i.test(k);
  const here = `${bucket ?? ""}/${prefix}`;

  async function act(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setErr(null);
    setNote(null);
    try {
      const msg = await fn();
      if (msg) setNote(msg);
      reload();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  function upload(files: File[]) {
    if (!bucket || !files.length) return;
    act("upload", async () => {
      const r = await api.uploadToStorage(bucket, prefix, files);
      const renamed = r.saved.filter((s) => s.renamed);
      return `Uploaded ${r.saved.length} file${r.saved.length === 1 ? "" : "s"} to ${here}.`
        + (renamed.length ? ` Kept both copies where a name was taken: ${renamed.map((s) => s.name).join(", ")}.` : "");
    });
  }

  async function askDeleteFolder(p: string) {
    if (!bucket) return;
    try {
      const s = await api.storageFolderSummary(bucket, p);
      setConfirm({ kind: "folder", prefix: p, files: s.files, size: s.size });
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <main className="layout storage">
      <section
        className={`panel storage-browser ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
        onDrop={(e) => { e.preventDefault(); setDragging(false); upload(Array.from(e.dataTransfer.files)); }}
      >
        <div className="panel-head">
          <div>
            <h2>Storage</h2>
            <p className="muted small">Files kept in object storage (MinIO). Drop files anywhere on this panel to upload them here.</p>
          </div>
          {buckets.length > 1 && (
            <select value={bucket ?? ""} onChange={(e) => { setBucket(e.target.value); open(""); }}>
              {buckets.map((b) => <option key={b}>{b}</option>)}
            </select>
          )}
        </div>

        <nav className="crumbs">
          <button className="btn btn-link" onClick={() => open("")}>{bucket ?? "…"}</button>
          {parts.map((p, i) => (
            <span key={i}>
              <span className="muted"> / </span>
              <button className="btn btn-link" onClick={() => open(parts.slice(0, i + 1).join("/") + "/")}>{p}</button>
            </span>
          ))}
        </nav>

        <div className="toolbar">
          <button className="btn" disabled={!!busy} onClick={() => fileInput.current?.click()}>
            {busy === "upload" ? "Uploading…" : "⬆ Upload files"}
          </button>
          <input ref={fileInput} type="file" multiple hidden onChange={(e) => { upload(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          <button className="btn btn-secondary" disabled={!!busy} onClick={() => setNewFolder("")}>＋ New folder</button>
          {prefix && (
            <>
              <a className="btn btn-secondary" href={api.downloadFolderUrl(bucket!, prefix)} title="Every file in this folder and its sub-folders, as one .zip">
                ⬇ Download folder (.zip)
              </a>
              <button className="btn btn-secondary danger-text" disabled={!!busy} onClick={() => askDeleteFolder(prefix)}>Delete folder…</button>
            </>
          )}
          {bucket && prefix && !prefix.startsWith("archive/") && onMakePipeline && (
            <button className="btn btn-secondary" onClick={() => onMakePipeline(bucket, prefix)}
              title="Every file that lands in this folder gets loaded into a table">
              Watch with a pipeline…
            </button>
          )}
        </div>

        {newFolder !== null && (
          <form className="inline-form" onSubmit={(e) => {
            e.preventDefault();
            const name = newFolder.trim();
            if (!name || !bucket) return;
            act("folder", async () => {
              const r = await api.createStorageFolder(bucket, prefix, name);
              setNewFolder(null);
              return `Created folder ${bucket}/${r.prefix}`;
            });
          }}>
            <span>📁</span>
            <input className="text-input" autoFocus value={newFolder} onChange={(e) => setNewFolder(e.target.value)} placeholder="Folder name" />
            <button className="btn" disabled={!newFolder.trim() || !!busy}>Create</button>
            <button type="button" className="btn btn-secondary" onClick={() => setNewFolder(null)}>Cancel</button>
          </form>
        )}

        {confirm?.kind === "folder" && (
          <div className="confirm">
            <p>
              Delete <code>{bucket}/{confirm.prefix}</code>
              {confirm.files ? <> and the <b>{confirm.files} file{confirm.files === 1 ? "" : "s"}</b> in it ({human(confirm.size)})</> : " (it's empty)"}?
              This can't be undone.
              {confirm.prefix.startsWith("archive/") && " These are the kept copies of loaded files; retrying those loads won't work afterwards."}
            </p>
            <div className="row-gap">
              <button className="btn btn-danger" disabled={!!busy} onClick={() => act("delete", async () => {
                const r = await api.deleteStorageFolder(bucket!, confirm.prefix);
                setConfirm(null);
                const parent = confirm.prefix.split("/").filter(Boolean).slice(0, -1).join("/");
                open(parent ? parent + "/" : "");
                return `Deleted ${confirm.prefix} (${r.deleted} file${r.deleted === 1 ? "" : "s"}).`;
              })}>Delete it</button>
              <button className="btn btn-secondary" onClick={() => setConfirm(null)}>Keep it</button>
            </div>
          </div>
        )}

        {note && <p className="ok-note">{note}</p>}
        {err && <p className="error">{err}</p>}
        {!folder ? (
          <p className="muted pad">Loading…</p>
        ) : (
          <div className="table-wrap">
            <table className="files">
              <thead><tr><th>Name</th><th className="num">Size</th><th>Modified</th></tr></thead>
              <tbody>
                {folder.folders.map((f) => (
                  <tr key={f} className="clickable" onClick={() => open(f)}>
                    <td>📁 {f.slice(folder.prefix.length).replace(/\/$/, "")}</td><td /><td />
                  </tr>
                ))}
                {folder.files.map((f) => (
                  <tr key={f.key} className={`clickable ${selected === f.key ? "selected" : ""}`} onClick={() => { setSelected(f.key); setConfirm(null); }}>
                    <td>📄 {f.name}</td>
                    <td className="num">{human(f.size)}</td>
                    <td>{ago(f.last_modified)}</td>
                  </tr>
                ))}
                {!folder.folders.length && !folder.files.length && (
                  <tr><td colSpan={3} className="muted">This folder is empty. Upload files or drop them here.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
        {dragging && <div className="drop-hint">Drop to upload into <code>{here}</code></div>}
      </section>

      <section className="panel">
        {!selected ? (
          <p className="muted">Pick a file to see what's inside.</p>
        ) : !preview ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <div className="detail-head">
              <div>
                <h2>{preview.info.original_filename ?? selected.split("/").pop()}</h2>
                <div className="source-meta">
                  <code>{selected}</code>
                  <span>{human(preview.info.size)}</span>
                  <span>{new Date(preview.info.last_modified).toLocaleString()}</span>
                </div>
              </div>
              <div className="actions">
                <a className="btn btn-secondary" href={api.downloadUrl(bucket!, selected)}>⬇ Download</a>
                {isCsv(selected) && <button className="btn" onClick={() => onLoadFile(selected)}>Load into a table…</button>}
                <button className="btn btn-secondary danger-text" onClick={() => setConfirm({ kind: "file", key: selected })}>Delete…</button>
              </div>
            </div>
            {confirm?.kind === "file" && confirm.key === selected && (
              <div className="confirm">
                <p>
                  Delete <code>{selected}</code>? This can't be undone.
                  {selected.startsWith("archive/") && " It's the kept copy of a loaded file; retrying that load won't work afterwards."}
                </p>
                <div className="row-gap">
                  <button className="btn btn-danger" onClick={() => act("delete", async () => {
                    await api.deleteStorageObject(bucket!, selected);
                    setConfirm(null);
                    setSelected(null);
                    return `Deleted ${selected}.`;
                  })}>Delete it</button>
                  <button className="btn btn-secondary" onClick={() => setConfirm(null)}>Keep it</button>
                </div>
              </div>
            )}
            {preview.is_text ? (
              <>
                <pre className="file-preview">{preview.lines.join("\n")}</pre>
                {preview.truncated && <p className="muted small">Showing the start of the file only.</p>}
              </>
            ) : (
              <p className="muted pad">Not a text file, so there's no preview.</p>
            )}
          </>
        )}
      </section>
    </main>
  );
}
