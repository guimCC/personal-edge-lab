import { useState } from "react";

import type { Alerts, Health } from "../../api/contracts";
import { duration, elapsed, formatDateTime, humanize } from "../../shared/format";
import {
  overallSystemLabel,
  statusTone,
  type ServiceStatus,
} from "../../shared/status";

interface OperationsPanelProps {
  health?: Health;
  alerts?: Alerts;
  alertsPending: boolean;
  alertsFailed: boolean;
  disconnected: boolean;
}

function serviceStatuses(
  health: Health | undefined,
  disconnected: boolean,
): ServiceStatus[] {
  if (!health) {
    return [
      {
        label: "API",
        value: disconnected ? "Unreachable" : "Connecting",
        detail: disconnected ? "No response from RUBIK" : "Waiting for first response",
        tone: disconnected ? "bad" : "unknown",
      },
      { label: "Collector", value: "Unknown", detail: "API status required", tone: "unknown" },
      { label: "ESP32", value: "Unknown", detail: "Collector status required", tone: "unknown" },
      { label: "Telemetry", value: "Unknown", detail: "No reading status", tone: "unknown" },
    ];
  }
  return [
    {
      label: "API",
      value: disconnected ? "Interrupted" : "Online",
      detail: disconnected ? "Showing last good response" : `Version ${health.version}`,
      tone: disconnected ? "warn" : "good",
    },
    {
      label: "Collector",
      value: humanize(health.collector.status),
      detail:
        health.collector.heartbeat_age_seconds == null
          ? "No heartbeat yet"
          : `Heartbeat ${elapsed(health.collector.heartbeat_age_seconds)}`,
      tone: statusTone(health.collector.status),
    },
    {
      label: "ESP32",
      value: humanize(health.edge_node.status),
      detail: `Last success ${formatDateTime(health.edge_node.last_success_at_utc)}`,
      tone: statusTone(health.edge_node.status),
    },
    {
      label: "Telemetry",
      value: humanize(health.telemetry.status),
      detail: elapsed(health.telemetry.age_seconds),
      tone: statusTone(health.telemetry.status),
    },
  ];
}

export function OperationalNotice({ alerts }: { alerts?: Alerts }) {
  const active = alerts?.incidents.filter((incident) => incident.status === "active") ?? [];
  const suspect = alerts?.states.filter((state) => state.lifecycle === "suspect") ?? [];

  if (active.length === 0 && suspect.length === 0) return null;

  return (
    <section className="operational-notice" aria-label="Active operational incidents">
      {active.map((incident) => (
        <article role="alert" key={incident.id}>
          <span>ACTIVE / {humanize(incident.alert_type)}</span>
          <strong>{incident.evidence_message}</strong>
          <small>
            {duration(incident.duration_seconds)} · Since{" "}
            {formatDateTime(incident.alerting_at_utc)}
          </small>
        </article>
      ))}
      {suspect.map((state) => (
        <article className="notice-suspect" key={state.alert_type}>
          <span>SUSPECT / {humanize(state.alert_type)}</span>
          <strong>{state.evidence_message}</strong>
          <small>Observed {formatDateTime(state.last_observed_at_utc)}</small>
        </article>
      ))}
    </section>
  );
}

export function OperationsPanel({
  health,
  alerts,
  alertsPending,
  alertsFailed,
  disconnected,
}: OperationsPanelProps) {
  const statuses = serviceStatuses(health, disconnected);
  const active = alerts?.incidents.filter((incident) => incident.status === "active") ?? [];
  const recovered =
    alerts?.incidents.filter((incident) => incident.status === "recovered").slice(0, 5) ?? [];
  const requiresAttention =
    disconnected ||
    health?.status === "degraded" ||
    alerts?.status === "alerting" ||
    alerts?.status === "suspect";
  const label = overallSystemLabel(health, disconnected);
  const [manuallyExpanded, setManuallyExpanded] = useState(false);
  const expanded = requiresAttention || manuallyExpanded;

  return (
    <section className="operations-section" id="system" aria-labelledby="system-title">
      <details
        className="operations-disclosure"
        open={expanded}
        onToggle={(event) => {
          if (!requiresAttention) setManuallyExpanded(event.currentTarget.open);
        }}
      >
        <summary>
          <div>
            <p className="overline">RUBIK OPERATIONS</p>
            <h2 id="system-title">System</h2>
          </div>
          <div className="operations-summary">
            <span
              className={`signal signal-${
                disconnected ? "bad" : statusTone(health?.status ?? "unknown")
              }`}
            />
            <strong>{label}</strong>
            <small>{requiresAttention ? "Details open" : "Show technical details"}</small>
          </div>
        </summary>

        <div className="service-ledger" aria-label="Platform health">
          {statuses.map((status, index) => (
            <article key={status.label}>
              <span className="service-index">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <span>{status.label}</span>
                <strong>{status.value}</strong>
              </div>
              <small>{status.detail}</small>
              <span className={`signal signal-${status.tone}`} aria-hidden="true" />
            </article>
          ))}
        </div>

        <div className="incident-ledger">
          <div className="incident-ledger-heading">
            <h3>Durable incident record</h3>
            <span className={`status-text status-${statusTone(alerts?.status ?? "unknown")}`}>
              {alertsFailed ? "connection lost" : humanize(alerts?.status ?? "checking")}
            </span>
          </div>

          {alertsPending && !alerts ? (
            <p>Loading operational alert state…</p>
          ) : alertsFailed && !alerts ? (
            <p className="data-error" role="alert">
              Alert state is unavailable.
            </p>
          ) : active.length > 0 ? (
            <p>
              {active.length} active incident{active.length === 1 ? "" : "s"} shown above · Last
              evaluated {formatDateTime(alerts?.evaluator_last_run_at_utc)}
            </p>
          ) : recovered.length === 0 ? (
            <p>
              No active operational incidents · Evaluator last ran{" "}
              {formatDateTime(alerts?.evaluator_last_run_at_utc)}
            </p>
          ) : (
            recovered.map((incident) => (
              <details className="recovery-row" key={incident.id}>
                <summary>
                  <strong>{humanize(incident.alert_type)}</strong>
                  <span>Recovered {formatDateTime(incident.recovered_at_utc)}</span>
                </summary>
                <p>
                  Active for {duration(incident.duration_seconds)} ·{" "}
                  {incident.evidence_message}
                </p>
              </details>
            ))
          )}
        </div>
      </details>
    </section>
  );
}
