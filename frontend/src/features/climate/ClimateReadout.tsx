import type { Health, Reading } from "../../api/contracts";
import { elapsed, formatDateTime, humanize } from "../../shared/format";
import { statusTone } from "../../shared/status";

interface ClimateReadoutProps {
  health?: Health;
  latest?: Reading | null;
  pending: boolean;
}

export function ClimateReadout({ health, latest, pending }: ClimateReadoutProps) {
  const freshness = health?.telemetry.status ?? "checking";

  return (
    <section className="climate-readout" aria-labelledby="temperature-title">
      <div className="module-heading">
        <div>
          <p className="overline">MODULE 01 / CLIMATE</p>
          <h1 id="temperature-title">Room climate</h1>
        </div>
        <span className={`inline-status status-${statusTone(freshness)}`}>
          <span className="signal" aria-hidden="true" />
          {humanize(freshness)}
        </span>
      </div>

      <div className="reading-body">
        <p className="reading-label">Current temperature</p>
        {pending ? (
          <div className="temperature-loading" aria-label="Loading current temperature" />
        ) : latest ? (
          <>
            <div className="temperature-value">
              {latest.temperature_c.toFixed(1)}
              <span>°C</span>
            </div>
            <p className="reading-time">
              {elapsed(health?.telemetry.age_seconds)} ·{" "}
              {formatDateTime(latest.received_at_utc)}
            </p>
          </>
        ) : (
          <>
            <div className="temperature-value temperature-empty">—</div>
            <p className="reading-time">No stored reading for this device</p>
          </>
        )}
      </div>

      <dl className="reading-metadata">
        <div>
          <dt>Source</dt>
          <dd>{latest?.sensor ?? "—"}</dd>
        </div>
        <div>
          <dt>Device</dt>
          <dd>{health?.telemetry.device_id ?? latest?.device_id ?? "ac-controller-01"}</dd>
        </div>
      </dl>
    </section>
  );
}
