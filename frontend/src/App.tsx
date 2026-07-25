import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  getCommandHistory,
  getHealth,
  getLatest,
  getSeries,
  getSession,
  login,
  logout,
  sendCommand,
  type BrowserCommand,
  type CommandHistory,
  type CommandResponse,
  type Fan,
  type Health,
  type Session,
  type Vane,
  type WindowOption,
} from "./api";
import type { ChartPoint } from "./TemperatureChart";

const WINDOWS: WindowOption[] = ["1h", "6h", "24h"];
const FANS: Fan[] = ["auto", "low", "medium", "high", "max"];
const VANES: Vane[] = ["auto", "highest", "high", "middle", "low", "lowest", "swing"];
const TemperatureChart = lazy(() => import("./TemperatureChart"));

type StatusTone = "good" | "warn" | "bad" | "unknown";
type ControlResult =
  | { kind: "completed"; response: CommandResponse }
  | { kind: "unknown"; message: string }
  | { kind: "error"; message: string };

interface StatusCardProps {
  label: string;
  value: string;
  detail: string;
  tone: StatusTone;
}

interface ControlDefaults {
  temperature: number;
  fan: Fan;
  vane: Vane;
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

function LoginScreen({
  session,
  onAuthenticated,
}: {
  session: Session;
  onAuthenticated: (value: Session) => void;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      onAuthenticated(await login(password));
      setPassword("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 429) {
        setError(
          `Too many attempts. Try again in about ${caught.retryAfter ?? 900} seconds.`,
        );
      } else {
        setError("The password was not accepted.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="login-title">
        <p className="eyebrow">PERSONAL EDGE LAB · RUBIK</p>
        <h1 id="login-title">Owner sign in</h1>
        <p>Sign in to view telemetry and intentionally control the air conditioner.</p>
        <form onSubmit={submit}>
          <label htmlFor="owner-password">Password</label>
          <input
            id="owner-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
            required
          />
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <small>
          Authentication is protected by the trusted local HTTPS certificate. Controls are{" "}
          {session.controls_enabled ? "available after sign-in" : "currently disabled"}.
        </small>
      </section>
    </main>
  );
}

function lastRequestedDefaults(commands: CommandHistory | undefined): ControlDefaults {
  for (const command of commands?.items ?? []) {
    const payload = command.command_payload;
    if (
      command.command_type === "set_state" &&
      payload.power === true &&
      payload.mode === "cool" &&
      typeof payload.temperature_c === "number" &&
      payload.temperature_c >= 16 &&
      payload.temperature_c <= 31 &&
      typeof payload.fan === "string" &&
      FANS.includes(payload.fan as Fan) &&
      typeof payload.vertical_vane === "string" &&
      VANES.includes(payload.vertical_vane as Vane)
    ) {
      return {
        temperature: payload.temperature_c,
        fan: payload.fan as Fan,
        vane: payload.vertical_vane as Vane,
      };
    }
  }
  return { temperature: 24, fan: "auto", vane: "middle" };
}

function outcomeMessage(response: CommandResponse): string {
  const { audit, replayed } = response;
  const prefix = replayed ? "Recovered recorded result. " : "";
  switch (audit.outcome) {
    case "confirmed_success":
      return `${prefix}The ESP32 confirmed the command.`;
    case "rejected_locally":
      return `${prefix}RUBIK rejected the request before contacting the ESP32.`;
    case "node_unreachable":
      return `${prefix}The ESP32 could not be reached; the command was not confirmed.`;
    case "node_reported_failure":
      return `${prefix}The ESP32 reported that the command failed.`;
    case "timeout_unknown":
    case "response_unknown":
      return `${prefix}The command may have been transmitted, but its physical outcome is unknown. Do not automatically retry it.`;
    default:
      return `${prefix}The command is recorded as ${humanize(audit.outcome)}.`;
  }
}

function ControlPanel({
  csrfToken,
  commands,
  degraded,
  onCompleted,
}: {
  csrfToken: string;
  commands: CommandHistory | undefined;
  degraded: boolean;
  onCompleted: () => void;
}) {
  const defaults = useMemo(() => lastRequestedDefaults(commands), [commands]);
  const [temperature, setTemperature] = useState(defaults.temperature);
  const [fan, setFan] = useState<Fan>(defaults.fan);
  const [vane, setVane] = useState<Vane>(defaults.vane);
  const [review, setReview] = useState<BrowserCommand | null>(null);
  const [lastCommand, setLastCommand] = useState<BrowserCommand | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ControlResult | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const reviewTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (review) confirmRef.current?.focus();
  }, [review]);

  const openReview = (command: BrowserCommand, trigger: HTMLButtonElement) => {
    reviewTriggerRef.current = trigger;
    setReview(command);
    setLastCommand(command);
    setIdempotencyKey(crypto.randomUUID());
    setResult(null);
  };

  const closeReview = () => {
    setReview(null);
    requestAnimationFrame(() => reviewTriggerRef.current?.focus());
  };

  const submit = async () => {
    const command = review ?? lastCommand;
    if (!command || !idempotencyKey) return;
    setSubmitting(true);
    setResult(null);
    try {
      const response = await sendCommand(command, idempotencyKey, csrfToken);
      setResult({ kind: "completed", response });
      closeReview();
      onCompleted();
    } catch (caught) {
      if (!(caught instanceof ApiError) || caught.status === 503) {
        setResult({
          kind: "unknown",
          message:
            "RUBIK could not return a reliable result. The command may have been transmitted. Do not create a new command; you may check this same request safely.",
        });
      } else if (caught.status === 409) {
        setResult({
          kind: "error",
          message:
            "This request is already in progress, conflicts with its request key, or another command currently holds the device.",
        });
      } else if (caught.status === 429) {
        setResult({
          kind: "error",
          message: `Command limit reached. Wait about ${caught.retryAfter ?? 60} seconds.`,
        });
      } else {
        setResult({ kind: "error", message: `Command was not accepted (${caught.status}).` });
      }
      closeReview();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel control-panel" aria-labelledby="control-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">INTENTIONAL CONTROL</p>
          <h2 id="control-title">Air conditioner</h2>
          <p className="panel-note">
            Last requested settings — not current AC state. Browser control is limited to cool
            mode.
          </p>
        </div>
      </div>
      {degraded && (
        <div className="control-warning">
          Collector or ESP32 health is degraded. Stored health can lag recovery; controls remain
          available, but review the uncertainty carefully.
        </div>
      )}
      <div className="control-fields">
        <label>
          Mode
          <input value="Cool" disabled />
        </label>
        <label>
          Temperature
          <select
            value={temperature}
            onChange={(event) => setTemperature(Number(event.target.value))}
          >
            {Array.from({ length: 16 }, (_, index) => index + 16).map((value) => (
              <option key={value} value={value}>
                {value} °C
              </option>
            ))}
          </select>
        </label>
        <label>
          Fan
          <select value={fan} onChange={(event) => setFan(event.target.value as Fan)}>
            {FANS.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Vertical vane
          <select value={vane} onChange={(event) => setVane(event.target.value as Vane)}>
            {VANES.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="control-actions">
        <button
          className="primary-action"
          type="button"
          disabled={submitting}
          onClick={(event) =>
            openReview(
              {
                command_type: "set_state",
                state: {
                  power: true,
                  temperature_c: temperature,
                  mode: "cool",
                  fan,
                  vertical_vane: vane,
                },
              },
              event.currentTarget,
            )
          }
        >
          Review Set State
        </button>
        <button
          className="danger-action"
          type="button"
          disabled={submitting}
          onClick={(event) =>
            openReview({ command_type: "power_off" }, event.currentTarget)
          }
        >
          Review Power Off
        </button>
      </div>

      {result && (
        <div
          className={`command-result result-${result.kind}`}
          role={result.kind === "completed" ? "status" : "alert"}
        >
          <strong>
            {result.kind === "completed"
              ? humanize(result.response.audit.outcome)
              : result.kind === "unknown"
                ? "Physical outcome unknown"
                : "Command not submitted"}
          </strong>
          <p>
            {result.kind === "completed" ? outcomeMessage(result.response) : result.message}
          </p>
          {result.kind === "unknown" && (
            <button type="button" disabled={submitting} onClick={submit}>
              {submitting ? "Checking…" : "Check recorded result"}
            </button>
          )}
        </div>
      )}

      {review && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !submitting) closeReview();
          }}
        >
          <section
            className="review-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="review-title"
            onKeyDown={(event) => {
              if (event.key === "Escape" && !submitting) closeReview();
              if (
                event.key === "Tab" &&
                event.shiftKey &&
                document.activeElement === cancelRef.current
              ) {
                event.preventDefault();
                confirmRef.current?.focus();
              } else if (
                event.key === "Tab" &&
                !event.shiftKey &&
                document.activeElement === confirmRef.current
              ) {
                event.preventDefault();
                cancelRef.current?.focus();
              }
            }}
          >
            <p className="section-label">REVIEW REQUIRED</p>
            <h2 id="review-title">
              {review.command_type === "power_off" ? "Power off AC?" : "Set requested AC state?"}
            </h2>
            <p>
              This sends exactly one physical request. A timeout or interrupted response may leave
              the real outcome unknown, so the dashboard will not retry automatically.
            </p>
            <pre>{JSON.stringify(review, null, 2)}</pre>
            <div className="modal-actions">
              <button
                ref={cancelRef}
                type="button"
                disabled={submitting}
                onClick={closeReview}
              >
                Cancel
              </button>
              <button
                ref={confirmRef}
                className={review.command_type === "power_off" ? "danger-action" : "primary-action"}
                type="button"
                disabled={submitting}
                onClick={submit}
              >
                {submitting ? "Sending once…" : "Confirm once"}
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

function Dashboard({
  session,
  onLogout,
}: {
  session: Session;
  onLogout: () => Promise<void>;
}) {
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

  return (
    <main>
      <header className="masthead">
        <div>
          <p className="eyebrow">PERSONAL EDGE LAB · RUBIK</p>
          <h1>Room telemetry</h1>
        </div>
        <div className="owner-actions">
          {session.auth_enabled && <span>Owner · {session.actor_id}</span>}
          <button type="button" onClick={() => queryClient.invalidateQueries()}>
            Refresh now
          </button>
          {session.auth_enabled && (
            <button type="button" onClick={onLogout}>
              Log out
            </button>
          )}
        </div>
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

      {session.controls_enabled && session.csrf_token && (
        <ControlPanel
          key={commands.data?.items[0]?.id ?? "defaults"}
          csrfToken={session.csrf_token}
          commands={commands.data}
          degraded={health.data?.status === "degraded"}
          onCompleted={() => queryClient.invalidateQueries({ queryKey: ["commands"] })}
        />
      )}

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
            <p className="section-label">COMMAND AUDIT</p>
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
                    <dt>Source</dt>
                    <dd>{humanize(command.request_source)}</dd>
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
          Times shown in {timezone} · Dashboard refreshed{" "}
          {lastUpdated ? formatDateTime(new Date(lastUpdated).toISOString()) : "—"}
        </span>
      </footer>
    </main>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: getSession,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    const loseAuthentication = () => {
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== "session",
      });
      queryClient.setQueryData<Session>(["session"], (current) => ({
        authenticated: false,
        auth_enabled: current?.auth_enabled ?? true,
        controls_enabled: current?.controls_enabled ?? false,
      }));
      queryClient.invalidateQueries({ queryKey: ["session"] });
    };
    window.addEventListener("pel:unauthorized", loseAuthentication);
    return () => window.removeEventListener("pel:unauthorized", loseAuthentication);
  }, [queryClient]);

  const handleLogout = async () => {
    if (session.data?.csrf_token) {
      await logout(session.data.csrf_token);
    }
    queryClient.clear();
    await queryClient.invalidateQueries({ queryKey: ["session"] });
  };

  if (session.isPending) {
    return (
      <main className="login-shell">
        <div className="login-card">Establishing a secure RUBIK session…</div>
      </main>
    );
  }
  if (session.isError || !session.data) {
    return (
      <main className="login-shell">
        <div className="login-card" role="alert">
          RUBIK authentication is unavailable.
        </div>
      </main>
    );
  }
  if (session.data.auth_enabled && !session.data.authenticated) {
    return (
      <LoginScreen
        session={session.data}
        onAuthenticated={(value) => queryClient.setQueryData(["session"], value)}
      />
    );
  }
  return <Dashboard session={session.data} onLogout={handleLogout} />;
}
