import { lazy, Suspense } from "react";

import type { WindowOption } from "../../api/contracts";
import type { ChartPoint } from "./TemperatureChart";

const TemperatureChart = lazy(() => import("./TemperatureChart"));
const WINDOWS: WindowOption[] = ["1h", "6h", "24h"];

interface TemperatureHistoryProps {
  data: ChartPoint[];
  windowOption: WindowOption;
  timezone: string;
  sampleCount: number;
  pending: boolean;
  failed: boolean;
  onWindowChange: (window: WindowOption) => void;
}

export function TemperatureHistory({
  data,
  windowOption,
  timezone,
  sampleCount,
  pending,
  failed,
  onWindowChange,
}: TemperatureHistoryProps) {
  return (
    <section className="temperature-history" aria-labelledby="chart-title">
      <div className="section-heading">
        <div>
          <p className="overline">TEMPERATURE HISTORY</p>
          <h2 id="chart-title">Signal over time</h2>
          <p>Average and min–max range · {timezone}</p>
        </div>
        <div className="window-selector" aria-label="Temperature history window">
          {WINDOWS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={windowOption === value}
              onClick={() => onWindowChange(value)}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      {pending ? (
        <div className="data-state">Loading temperature history…</div>
      ) : failed ? (
        <div className="data-state data-error">Temperature history is unavailable.</div>
      ) : sampleCount === 0 ? (
        <div className="data-state">
          <span className="empty-rule" aria-hidden="true" />
          No samples exist in this time window.
        </div>
      ) : (
        <Suspense fallback={<div className="data-state">Preparing chart…</div>}>
          <TemperatureChart data={data} windowLabel={windowOption} />
        </Suspense>
      )}
      <p className="sample-count">
        {sampleCount} stored samples · Empty periods remain visible as gaps
      </p>
    </section>
  );
}
