import type { RunStatus } from "../api";

export function StatusPill({ status }: { status: RunStatus | undefined }) {
  if (!status) return <span className="pill pill-none">no runs</span>;
  return <span className={`pill pill-${status}`}>{status}</span>;
}
