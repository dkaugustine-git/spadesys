import { useEffect, useState } from "react";
import { api, isActive, type FileAnalysis } from "./api";
import { usePoll } from "./hooks";
import { SourceList } from "./components/SourceList";
import { SourceView } from "./components/SourceView";
import { ActivityFeed } from "./components/ActivityFeed";
import { LoadDialog } from "./components/LoadDialog";
import { StoragePage } from "./components/StoragePage";
import { DevDataPage } from "./components/DevDataPage";
import { DatabasesPage } from "./components/DatabasesPage";
import { ApiPage } from "./components/ApiPage";
import { PipelinesPage, type StoragePlace } from "./components/PipelinesPage";
import { PAGES, Sidebar, type Page } from "./components/Sidebar";

const pageFromHash = (): Page => {
  const h = window.location.hash.replace("#/", "").split("/")[0];
  return (PAGES.find((p) => p.key === h)?.key ?? "sources") as Page;
};

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [selected, setSelected] = useState<string | null>(null);
  const [activeHint, setActiveHint] = useState(false);
  // Files waiting for the user to decide what to do with them.
  const [pending, setPending] = useState<FileAnalysis[]>([]);
  const [pageError, setPageError] = useState<string | null>(null);
  // Storage tab -> "Watch this folder with a pipeline" opens the new-pipeline form filled in.
  const [pipelinePrefill, setPipelinePrefill] = useState<StoragePlace | null>(null);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = (p: Page) => {
    window.location.hash = p === "sources" ? "#/" : `#/${p}`;
    setPage(p);
  };

  const sources = usePoll(api.sources, activeHint ? 1500 : 8000);
  const anyActive = !!sources.data?.some((s) => isActive(s.last_run));
  if (anyActive !== activeHint) setActiveHint(anyActive);

  const current = pending[0];

  return (
    <div className="app">
      <Sidebar page={page} go={go} />
      <div className="content">

      {pageError && <p className="error page-error">{pageError} <button className="btn btn-link" onClick={() => setPageError(null)}>dismiss</button></p>}

      {page === "pipelines" ? (
        <PipelinesPage prefill={pipelinePrefill} onPrefillUsed={() => setPipelinePrefill(null)}
          onOpenTable={(id) => { go("sources"); setSelected(id); }} />
      ) : page === "api" ? (
        <ApiPage />
      ) : page === "databases" ? (
        <DatabasesPage />
      ) : page === "devdata" ? (
        <DevDataPage />
      ) : page === "storage" ? (
        <StoragePage
          onMakePipeline={(bucket, prefix) => { setPipelinePrefill({ bucket, prefix }); go("pipelines"); }}
          onLoadFile={(key) =>
            api.analyzeStored(key).then((a) => setPending((p) => [...p, a]), (e) => setPageError(String(e)))
          }
        />
      ) : (
        <main className={`layout ${selected ? "has-selection" : ""}`}>
          <SourceList
            sources={sources.data}
            error={sources.error}
            selected={selected}
            onSelect={setSelected}
            onChanged={sources.refresh}
            onShowActivity={() => setSelected(null)}
            onStaged={(a) => setPending((p) => [...p, a])}
          />
          {selected ? (
            <SourceView
              key={selected}
              id={selected}
              onBack={() => setSelected(null)}
              onDeleted={() => {
                setSelected(null);
                sources.refresh();
              }}
              onChanged={sources.refresh}
            />
          ) : (
            <section className="panel empty-state">
              <ActivityFeed />
            </section>
          )}
        </main>
      )}

      </div>

      {current && (
        <LoadDialog
          key={current.key}
          analysis={current}
          onLater={() => setPending((p) => p.slice(1))}
          onDone={(source) => {
            setPending((p) => p.slice(1));
            sources.refresh();
            go("sources");
            setSelected(source.id);
          }}
        />
      )}
    </div>
  );
}
