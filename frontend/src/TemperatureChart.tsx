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
    <div className="chart" aria-label={`${windowLabel} temperature chart`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 16, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="2 6" vertical={false} />
          <XAxis
            dataKey="timestamp"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatTime}
            minTickGap={44}
          />
          <YAxis width={50} unit="°" domain={["auto", "auto"]} />
          <Tooltip
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
            stroke="var(--chart-line)"
            strokeWidth={2.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
