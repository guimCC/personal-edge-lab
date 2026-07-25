import type { CommandHistory } from "../../api/contracts";
import { formatDateTime, formatTime, humanize } from "../../shared/format";
import { statusTone } from "../../shared/status";

interface ActivityFeedProps {
  commands?: CommandHistory;
  pending: boolean;
  failed: boolean;
}

function commandSummary(command: CommandHistory["items"][number]): string {
  if (command.command_type === "power_off") return "Power off requested";
  const temperature = command.command_payload.temperature_c;
  if (typeof temperature === "number") {
    return `Climate settings requested · ${temperature} °C`;
  }
  return `${humanize(command.command_type)} requested`;
}

export function ActivityFeed({ commands, pending, failed }: ActivityFeedProps) {
  const items = commands?.items ?? [];
  const visibleItems = items.slice(0, 3);

  return (
    <section className="activity-section" id="activity" aria-labelledby="activity-title">
      <div className="section-heading">
        <div>
          <p className="overline">CROSS-LAB RECORD</p>
          <h2 id="activity-title">Recent activity</h2>
          <p>Recorded requests, not inferred physical device state.</p>
        </div>
        <span className="section-count">{commands?.count ?? 0} EVENTS</span>
      </div>

      {pending ? (
        <div className="activity-state">Loading recent activity…</div>
      ) : failed ? (
        <div className="activity-state data-error">Activity is unavailable.</div>
      ) : items.length === 0 ? (
        <div className="activity-state">No device activity has been recorded yet.</div>
      ) : (
        <>
          <div className="activity-list">
            {visibleItems.map((command) => (
              <details className="activity-row" key={command.id}>
                <summary>
                  <time dateTime={command.requested_at_utc}>
                    {formatTime(command.requested_at_utc)}
                  </time>
                  <div>
                    <strong>{commandSummary(command)}</strong>
                    <span>
                      {humanize(command.request_source)} ·{" "}
                      {formatDateTime(command.requested_at_utc)}
                    </span>
                  </div>
                  <span className={`event-outcome status-${statusTone(command.outcome)}`}>
                    {humanize(command.outcome)}
                  </span>
                </summary>
                <dl className="activity-detail">
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

          {items.length > visibleItems.length && (
            <details className="activity-archive">
              <summary>Show {items.length - visibleItems.length} older events</summary>
              <div className="activity-list">
                {items.slice(visibleItems.length).map((command) => (
                  <details className="activity-row" key={command.id}>
                    <summary>
                      <time dateTime={command.requested_at_utc}>
                        {formatTime(command.requested_at_utc)}
                      </time>
                      <div>
                        <strong>{commandSummary(command)}</strong>
                        <span>{formatDateTime(command.requested_at_utc)}</span>
                      </div>
                      <span className={`event-outcome status-${statusTone(command.outcome)}`}>
                        {humanize(command.outcome)}
                      </span>
                    </summary>
                    <dl className="activity-detail">
                      <div>
                        <dt>Payload</dt>
                        <dd>{JSON.stringify(command.command_payload)}</dd>
                      </div>
                    </dl>
                  </details>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </section>
  );
}
