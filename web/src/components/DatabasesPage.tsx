import { useEffect, useState } from "react";
import { api } from "../api";

/** CloudBeaver (the web version of DBeaver) inside Spadesys, with every database Spadesys knows about. */
export function DatabasesPage() {
  const [status, setStatus] = useState<{ up: boolean; connections: string[] } | null>(null);
  const [frameKey, setFrameKey] = useState(0);

  // Poll until CloudBeaver is up (it restarts for ~20s whenever the database list changes).
  useEffect(() => {
    let stop = false;
    let wasUp = true;
    const tick = () =>
      api.cloudbeaver().then(
        (s) => {
          if (stop) return;
          if (s.up && !wasUp) setFrameKey((k) => k + 1); // came back: reload the frame
          wasUp = s.up;
          setStatus(s);
        },
        () => !stop && setStatus({ up: false, connections: [] }),
      );
    tick();
    const t = setInterval(tick, 4000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  return (
    <main className="framed">
      <div className="framed-bar">
        <span className="muted small">
          {status ? `${status.connections.length} database${status.connections.length === 1 ? "" : "s"}: ${status.connections.join(", ")}` : "Checking…"}
        </span>
        <span className="spacer" />
        <button className="btn" onClick={() => setFrameKey((k) => k + 1)}>Reload</button>
        <a className="btn" href="/cloudbeaver/" target="_blank" rel="noreferrer">Open in a new window</a>
      </div>
      {status && !status.up ? (
        <section className="panel empty-state">
          <h2>CloudBeaver is starting…</h2>
          <p className="muted">
            It restarts for about 20 seconds whenever the list of databases changes (for example after you save a connection on the Dev data tab).
            This page will show it as soon as it's back.
          </p>
        </section>
      ) : (
        <iframe key={frameKey} className="framed-frame" src="/cloudbeaver/" title="CloudBeaver" />
      )}
    </main>
  );
}
