import { useState, type ReactNode } from "react";
import { HealthBadge } from "./HealthBadge";

export type Page = "sources" | "pipelines" | "storage" | "devdata" | "databases" | "api";

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    {d}
  </svg>
);

export const PAGES: { key: Page; label: string; hint: string; icon: ReactNode }[] = [
  { key: "sources", label: "Sources", hint: "Files you've loaded and the tables they became",
    icon: icon(<><path d="M4 13h4l2 3h4l2-3h4" /><path d="M5.5 5h13L20 13v6H4v-6z" /></>) },
  { key: "pipelines", label: "Pipelines", hint: "Folders that load into tables, on demand or by watching",
    icon: icon(<><circle cx="5" cy="6" r="2.2" /><circle cx="19" cy="18" r="2.2" /><path d="M7.2 6H14a3 3 0 0 1 3 3v0a3 3 0 0 1-3 3h-4a3 3 0 0 0-3 3v0a3 3 0 0 0 3 3h6.8" /></>) },
  { key: "storage", label: "Storage", hint: "What's saved in MinIO",
    icon: icon(<><path d="M3 7l9-4 9 4-9 4z" /><path d="M3 12l9 4 9-4" /><path d="M3 17l9 4 9-4" /></>) },
  { key: "devdata", label: "Dev data", hint: "Make fake rows for a table",
    icon: icon(<><path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z" /><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" /></>) },
  { key: "databases", label: "Databases", hint: "Browse every database (CloudBeaver)",
    icon: icon(<><ellipse cx="12" cy="5.5" rx="7" ry="2.5" /><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13" /><path d="M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" /></>) },
  { key: "api", label: "API", hint: "Every endpoint, with Try it out",
    icon: icon(<><path d="M8 7l-5 5 5 5" /><path d="M16 7l5 5-5 5" /><path d="M13.5 5l-3 14" /></>) },
];

function loadCollapsed() {
  try { return localStorage.getItem("spadesys.sidebar") === "collapsed"; } catch { return false; }
}

export function Sidebar({ page, go }: { page: Page; go: (p: Page) => void }) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const toggle = () => {
    setCollapsed(!collapsed);
    try { localStorage.setItem("spadesys.sidebar", collapsed ? "open" : "collapsed"); } catch { /* fine */ }
  };

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <span className="brand-mark" aria-hidden>♠</span>
        <span className="brand-name">Spadesys</span>
      </div>
      <nav className="side-nav">
        {PAGES.map((p) => (
          <button key={p.key} className={page === p.key ? "active" : ""} onClick={() => go(p.key)} title={collapsed ? `${p.label}: ${p.hint}` : p.hint}
            aria-current={page === p.key ? "page" : undefined}>
            {p.icon}
            <span className="side-label">{p.label}</span>
          </button>
        ))}
      </nav>
      <div className="side-foot">
        <HealthBadge />
        <button className="side-collapse" onClick={toggle} title={collapsed ? "Show labels" : "Icons only"} aria-label={collapsed ? "Show labels" : "Icons only"}>
          {icon(collapsed ? <path d="M9 6l6 6-6 6" /> : <path d="M15 6l-6 6 6 6" />)}
        </button>
      </div>
    </aside>
  );
}
