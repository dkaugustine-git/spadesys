import { api } from "../api";
import { usePoll } from "../hooks";

export function HealthBadge() {
  const { data, error } = usePoll(api.health, 15000);
  const state = error ? "down" : !data ? "pending" : data.status === "ok" ? "ok" : "warn";
  const label = error ? "API unreachable" : !data ? "Connecting…" : data.status === "ok" ? "All systems ok" : "Degraded";
  const title = error ?? (data ? Object.entries(data.checks).map(([k, v]) => `${k}: ${v}`).join("\n") : "");
  return (
    <span className={`health health-${state}`} title={title}>
      <span className="dot" /> <span className="health-label">{label}</span>
    </span>
  );
}
