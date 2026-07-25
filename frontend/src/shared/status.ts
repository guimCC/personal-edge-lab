import type { Health } from "../api/contracts";

export type StatusTone = "good" | "warn" | "bad" | "unknown";

export interface ServiceStatus {
  label: string;
  value: string;
  detail: string;
  tone: StatusTone;
}

export function statusTone(value: string): StatusTone {
  if (
    ["healthy", "recovered", "fresh", "running", "reachable", "confirmed_success"].includes(
      value,
    )
  ) {
    return "good";
  }
  if (
    [
      "unreachable",
      "stopped",
      "rejected_locally",
      "node_unreachable",
      "node_reported_failure",
      "alerting",
    ].includes(value)
  ) {
    return "bad";
  }
  if (
    [
      "degraded",
      "suspect",
      "stale",
      "pending",
      "no_data",
      "timeout_unknown",
      "response_unknown",
    ].includes(value)
  ) {
    return "warn";
  }
  return "unknown";
}

export function overallSystemLabel(
  health: Health | undefined,
  disconnected: boolean,
): string {
  if (disconnected) return "Connection interrupted";
  if (!health) return "Checking RUBIK";
  if (health.status === "healthy") return "All systems operational";
  if (health.alerts.active_count > 0) {
    return `${health.alerts.active_count} active incident${
      health.alerts.active_count === 1 ? "" : "s"
    }`;
  }
  return "System requires attention";
}
