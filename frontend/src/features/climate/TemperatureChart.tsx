import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface ChartPoint {
  timestamp: number;
  average: number | null;
  range: [number, number] | null;
  samples: number;
}

interface TemperatureChartProps {
  data: ChartPoint[];
  windowLabel: string;
}

function formatTime(value: number): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDateTime(value: number): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

export default function TemperatureChart({ data, windowLabel }: TemperatureChartProps) {
  return (
    <div className="temperature-chart" aria-label={`${windowLabel} temperature chart`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 18, right: 8, bottom: 0, left: -14 }}>
          <CartesianGrid stroke="var(--line-subtle)" vertical={false} />
          <XAxis
            dataKey="timestamp"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatTime}
            minTickGap={44}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
          />
          <YAxis
            width={48}
            unit="°"
            domain={["auto", "auto"]}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--ink)",
              border: 0,
              borderRadius: 0,
              color: "var(--paper)",
              fontSize: 12,
            }}
            labelFormatter={(value) => formatDateTime(Number(value))}
            formatter={(value, name) => {
              if (name === "range" && Array.isArray(value)) {
                return [`${value[0].toFixed(1)}–${value[1].toFixed(1)} °C`, "Range"];
              }
              return [`${Number(value).toFixed(2)} °C`, "Average"];
            }}
          />
          <Area
            dataKey="range"
            stroke="none"
            fill="var(--chart-range)"
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="average"
            stroke="var(--module-accent)"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
