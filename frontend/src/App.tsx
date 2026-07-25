import { lazy, Suspense, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getCommandHistory,
  getHealth,
  getLatest,
  getSeries,
  type Health,
  type WindowOption,
} from "./api";
import type { ChartPoint } from "./TemperatureChart";

const WINDOWS: WindowOption[] = ["1h", "6h", "24h"];
const TemperatureChart = lazy(() => import("./TemperatureChart"));

type StatusTone = "good" | "warn" | "bad" | "unknown";

interface StatusCardProps {
  label: string;
  value: string;
  detail: string;
  tone: StatusTone;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function elapsed(seconds: number | null | undefined): string {
  if (seconds == null) return "No data yet";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${(seconds / 3600).toFixed(1)}h ago`;
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function statusTone(value: string): StatusTone {
  if (["healthy", "fresh", "running", "reachable", "confirmed_success"].includes(value)) {
    return "good";
  }
  if (
    [
      "unreachable",
      "stopped",
      "rejected_locally",
      "node_unreachable",
      "node_reported_failure",
    ].includes(value)
  ) {
    return "bad";
  }
  if (
    ["degraded", "stale", "pending", "no_data", "timeout_unknown", "response_unknown"].includes(
      value,
    )
  ) {
    return "warn";
  }
  return "unknown";
}

function StatusCard({ label, value, detail, tone }: StatusCardProps) {
  return (
    <article className={`status-card status-${tone}`}>
      <div className="status-heading">
        <span className="status-dot" aria-hidden="true" />
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function serviceCards(health: Health | undefined, disconnected: boolean): StatusCardProps[] {
  if (!health) {
    return [
      {
        label: "API",
        value: disconnected ? "Unreachable" : "Connecting",
        detail: disconnected ? "No response from RUBIK" : "Waiting for first response",
        tone: disconnected ? "bad" : "unknown",
      },
      {
        label: "Collector",
        value: "Unknown",
        detail: "API status required",
        tone: "unknown",
      },
      {
        label: "ESP32",
        value: "Unknown",
        detail: "Collector status required",
        tone: "unknown",
      },
      {
        label: "Telemetry",
        value: "Unknown",
        detail: "No reading status",
        tone: "unknown",
      },
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

export default function App() {
  const [windowOption, setWindowOption] = useState<WindowOption>("6h");
  const queryClient = useQueryClient();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 15_000,
  });
  const latest = useQuery({
    queryKey: ["latest"],
    queryFn: getLatest,
    refetchInterval: 15_000,
  });
  const series = useQuery({
    queryKey: ["series", windowOption],
    queryFn: () => getSeries(windowOption),
    refetchInterval: 60_000,
  });
  const commands = useQuery({
    queryKey: ["commands"],
    queryFn: getCommandHistory,
    refetchInterval: 60_000,
  });

  const disconnected = health.isError || latest.isError;
  const statuses = serviceCards(health.data, disconnected);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const chartData = useMemo<ChartPoint[]>(
    () =>
      (series.data?.items ?? []).map((item) => ({
        timestamp: new Date(item.bucket_start_at_utc).getTime(),
        average: item.temperature_average_c,
        range:
          item.temperature_minimum_c == null || item.temperature_maximum_c == null
            ? null
            : [item.temperature_minimum_c, item.temperature_maximum_c],
        samples: item.sample_count,
      })),
    [series.data],
  );
  const lastUpdated = Math.max(
    health.dataUpdatedAt,
    latest.dataUpdatedAt,
    series.dataUpdatedAt,
    commands.dataUpdatedAt,
  );

  const refresh = () => queryClient.invalidateQueries();

  return (
    <main>
      <header className="masthead">
        <div>
          <p className="eyebrow">PERSONAL EDGE LAB · RUBIK</p>
          <h1>Room telemetry</h1>
        </div>
        <button className="refresh-button" type="button" onClick={refresh}>
          Refresh now
        </button>
      </header>

      {disconnected && (
        <div className="connection-banner" role="alert">
          RUBIK did not answer the latest request. Last confirmed data stays visible with its
          original timestamp.
        </div>
      )}

      <section className="overview" aria-labelledby="temperature-title">
        <div className="temperature-block">
          <p id="temperature-title" className="section-label">
            CURRENT TEMPERATURE
          </p>
          {latest.isPending ? (
            <div className="temperature-loading" aria-label="Loading current temperature" />
          ) : latest.data ? (
            <>
              <div className="temperature-value">
                {latest.data.temperature_c.toFixed(1)}
                <span>°C</span>
              </div>
              <p className="temperature-meta">
                Received {formatDateTime(latest.data.received_at_utc)}
              </p>
            </>
          ) : (
            <>
              <div className="temperature-value temperature-empty">—</div>
              <p className="temperature-meta">No stored reading for this device</p>
            </>
          )}
        </div>
        <div className="freshness-block">
          <span
            className={`freshness-chip status-${statusTone(
              health.data?.telemetry.status ?? "unknown",
            )}`}
          >
            {humanize(health.data?.telemetry.status ?? "checking")}
          </span>
          <p>{elapsed(health.data?.telemetry.age_seconds)}</p>
          <small>Device · {health.data?.telemetry.device_id ?? "ac-controller-01"}</small>
        </div>
      </section>

      <section className="status-grid" aria-label="Platform health">
        {statuses.map((status) => (
          <StatusCard key={status.label} {...status} />
        ))}
      </section>

      <section className="panel chart-panel" aria-labelledby="chart-title">
        <div className="panel-heading">
          <div>
            <p className="section-label">TEMPERATURE HISTORY</p>
            <h2 id="chart-title">Signal over time</h2>
            <p className="panel-note">
              Average with min–max range · Times shown in {timezone}
            </p>
          </div>
          <div className="window-selector" aria-label="Temperature history window">
            {WINDOWS.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={windowOption === value}
                onClick={() => setWindowOption(value)}
              >
                {value}
              </button>
            ))}
          </div>
        </div>

        {series.isPending ? (
          <div className="chart-state">Loading temperature history…</div>
        ) : series.isError ? (
          <div className="chart-state chart-error">Temperature history is unavailable.</div>
        ) : series.data?.sample_count === 0 ? (
          <div className="chart-state">No samples exist in this time window.</div>
        ) : (
          <Suspense fallback={<div className="chart-state">Preparing chart…</div>}>
            <TemperatureChart data={chartData} windowLabel={windowOption} />
          </Suspense>
        )}
        <p className="sample-count">
          {series.data?.sample_count ?? 0} stored samples · Empty periods remain visible as gaps
        </p>
      </section>

      <section className="panel audit-panel" aria-labelledby="audit-title">
        <div className="panel-heading">
          <div>
            <p className="section-label">READ-ONLY AUDIT</p>
            <h2 id="audit-title">Recent AC commands</h2>
            <p className="panel-note">
              Historical requests only. This is not the air conditioner’s current state.
            </p>
          </div>
        </div>
        {commands.isPending ? (
          <div className="audit-state">Loading command history…</div>
        ) : commands.isError ? (
          <div className="audit-state chart-error">Command history is unavailable.</div>
        ) : commands.data?.items.length === 0 ? (
          <div className="audit-state">No AC commands have been audited yet.</div>
        ) : (
          <div className="audit-list">
            {commands.data?.items.map((command) => (
              <details key={command.id} className="audit-row">
                <summary>
                  <div>
                    <strong>{humanize(command.command_type)}</strong>
                    <span>{formatDateTime(command.requested_at_utc)}</span>
                  </div>
                  <span className={`outcome status-${statusTone(command.outcome)}`}>
                    {humanize(command.outcome)}
                  </span>
                </summary>
                <dl>
                  <div>
                    <dt>Payload</dt>
                    <dd>{JSON.stringify(command.command_payload)}</dd>
                  </div>
                  <div>
                    <dt>Completed</dt>
                    <dd>{formatDateTime(command.completed_at_utc)}</dd>
                  </div>
                  {command.error_message && (
                    <div>
                      <dt>Failure</dt>
                      <dd>{command.error_message}</dd>
                    </div>
                  )}
                </dl>
              </details>
            ))}
          </div>
        )}
      </section>

      <footer>
        <span>Personal Edge Lab API {health.data?.version ?? "—"}</span>
        <span>
          Dashboard refreshed {lastUpdated ? formatDateTime(new Date(lastUpdated).toISOString()) : "—"}
        </span>
      </footer>
    </main>
  );
}
