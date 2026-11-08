import { useRef, useState } from "react";
import { api, type FileAnalysis, type Source } from "../api";
import { ago, num } from "../format";
import { StatusPill } from "./StatusPill";

interface Props {
  sources: Source[] | null;
  error: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onChanged: () => void;
  onShowActivity: () => void;
  onStaged: (a: FileAnalysis) => void;
}

export function SourceList({ sources, error, selected, onSelect, onChanged, onShowActivity, onStaged }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setActionError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function uploadFiles(files: FileList | null) {
    if (!files?.length) return;
    await act("Uploading…", async () => {
      for (const f of Array.from(files)) onStaged(await api.stageUpload(f));
    });
  }

  return (
    <section className="panel sources">
      <div className="panel-head">
        <h2>Sources</h2>
        <span className="muted">{sources ? sources.length : "…"}</span>
      </div>

      <div
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          uploadFiles(e.dataTransfer.files);
        }}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      >
        <input
          ref={input}
          type="file"
          accept=".csv,.tsv,.txt,text/csv"
          multiple
          hidden
          onChange={(e) => {
            uploadFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <strong>{busy ?? "Drop CSV files here"}</strong>
        <span className="muted">or click to browse</span>
      </div>

      <button
        className="btn btn-secondary full"
        disabled={!!busy}
        onClick={() => {
          onShowActivity();
          act("Generating…", () => api.generateCommerce());
        }}
      >
        ✨ Generate sample commerce data
      </button>

      {(actionError || error) && <p className="error">{actionError ?? error}</p>}

      <ul className="source-list">
        {sources?.map((s) => (
          <li key={s.id}>
            <button className={`source-item ${selected === s.id ? "selected" : ""}`} onClick={() => onSelect(s.id)}>
              <div className="source-row">
                <span className="source-name">{s.name}</span>
                <StatusPill status={s.last_run?.status} />
              </div>
              <div className="source-meta">
                <code>raw.{s.table_name}</code>
                <span>{num(s.row_count)} rows</span>
                <span>{ago(s.last_run?.created_at ?? s.created_at)}</span>
              </div>
            </button>
          </li>
        ))}
        {sources?.length === 0 && <li className="muted pad">No sources yet.</li>}
      </ul>
    </section>
  );
}
