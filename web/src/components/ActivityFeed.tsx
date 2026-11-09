import { useEffect, useRef, useState } from "react";
import { api, type ActivityEvent } from "../api";

/** Plain-English explanation of each step, shown on hover and in the legend. */
export const STAGES: Record<string, { label: string; why: string }> = {
  generate: { label: "Generate", why: "Creating fake test data so you have something to work with." },
  upload: { label: "Upload", why: "Your file arrived at the server." },
  store: { label: "Store", why: "The original file is kept untouched, so any load can be re-run later." },
  decide: { label: "Your choice", why: "What you decided to do with the file." },
  queue: { label: "Queue", why: "The work is handed to a background worker, so the page doesn't have to wait." },
  start: { label: "Start", why: "A background worker took the job." },
  download: { label: "Fetch", why: "The worker pulls the original file back out of storage." },
  parse: { label: "Read", why: "Turning the CSV text into rows and columns." },
  validate: { label: "Check", why: "Basic sanity checks: is there a header? Are there rows?" },
  infer: { label: "Types", why: "Guessing what each column holds: number, date, yes/no, or text." },
  hash: { label: "Fingerprint", why: "Each row gets a fingerprint so loading the same data twice doesn't create duplicates." },
  load: { label: "Save", why: "Writing the rows into a database table you can query." },
  done: { label: "Done", why: "All steps finished." },
  error: { label: "Error", why: "Something went wrong. The message says what." },
  connect: { label: "Connect", why: "A database connection was saved." },
  schema: { label: "Schema", why: "Read a table's columns and types from a database." },
  devdata: { label: "Dev data", why: "Fake rows were made from a column design." },
  delete: { label: "Delete", why: "A source was removed." },
  storage: { label: "Storage", why: "Something changed in storage: a folder made, files uploaded, exported, or deleted." },
  pipeline: { label: "Pipeline", why: "A pipeline checked its folder, picked up files, or was changed." },
  transform: { label: "Transform", why: "A transform was saved or run. Transforms read a table and write a clean copy; raw data is never changed." },
};

const time = (iso: string) => {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
};

interface Props {
  sourceId?: string;
  pipelineId?: string;
  extractId?: string;
  transformId?: string;
  title?: string;
  compact?: boolean;
}

export function ActivityFeed({ sourceId, pipelineId, extractId, transformId, title = "Activity", compact = false }: Props) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [clearedAt, setClearedAt] = useState(0);
  const lastId = useRef(0);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    lastId.current = 0;
    setEvents([]);
    let cancelled = false;
    async function tick() {
      try {
        const fresh = pipelineId
          ? await api.pipelineEvents(pipelineId, lastId.current)
          : extractId
          ? await api.extractEvents(extractId, lastId.current)
          : transformId
          ? await api.transformEvents(transformId, lastId.current)
          : await api.events({ afterId: lastId.current, sourceId });
        if (cancelled || !fresh.length) return;
        lastId.current = fresh[fresh.length - 1].id;
        setEvents((prev) => [...prev, ...fresh].slice(-500));
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }
    tick();
    const t = setInterval(tick, 1000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [sourceId, pipelineId, extractId, transformId]);

  // Keep scrolled to the newest line unless the user scrolled up to read.
  useEffect(() => {
    if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events]);

  const visible = events.filter((e) => e.id > clearedAt);

  return (
    <div className={`activity ${compact ? "compact" : ""}`}>
      {!compact && (
        <div className="panel-head">
          <div>
            <h2>{title}</h2>
            <p className="muted small">Every step the system takes, in order, as it happens. Hover a step name to see what it means.</p>
          </div>
          <span className="live"><span className="dot" /> live</span>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div
        className="feed"
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {visible.length === 0 && (
          <p className="muted pad">Nothing yet. Click <b>Generate sample commerce data</b> or drop a CSV, and watch this space.</p>
        )}
        {visible.map((e, i) => {
          const prev = visible[i - 1];
          const newJob = e.stage === "generate" || e.stage === "upload" || (prev && e.run_id && prev.run_id !== e.run_id && e.stage === "start");
          const stage = STAGES[e.stage] ?? { label: e.stage, why: "" };
          return (
            <div key={e.id} className={`line stage-${e.stage} ${newJob && i > 0 ? "gap" : ""}`}>
              <span className="t">{time(e.ts)}</span>
              <span className="stage" title={stage.why}>{stage.label}</span>
              <span className="msg">
                {e.source_name && <b>{e.source_name}: </b>}
                {e.message}
                {e.detail && (
                  <button className="btn btn-link more" onClick={() => setOpen(open === e.id ? null : e.id)}>
                    {open === e.id ? "hide" : "details"}
                  </button>
                )}
                {open === e.id && e.detail && <Detail d={e.detail} />}
              </span>
            </div>
          );
        })}
      </div>
      {!compact && visible.length > 0 && (
        <button className="btn btn-link small" onClick={() => setClearedAt(lastId.current)}>Clear view</button>
      )}
    </div>
  );
}

function Detail({ d }: { d: Record<string, unknown> }) {
  return (
    <dl className="detail-kv">
      {Object.entries(d).map(([k, v]) => (
        <div key={k}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd>
            {v && typeof v === "object" && !Array.isArray(v)
              ? Object.entries(v as Record<string, unknown>).map(([a, b]) => (
                  <span key={a} className="kv"><code>{a}</code> {String(b)}</span>
                ))
              : Array.isArray(v)
                ? v.length ? v.map((x) => <code key={String(x)} className="chip">{String(x)}</code>) : "none"
                : String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
