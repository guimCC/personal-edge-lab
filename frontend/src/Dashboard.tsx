import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAlerts,
  getCommandHistory,
  getHealth,
  getLatest,
  getSeries,
} from "./api/client";
import type { Session, WindowOption } from "./api/contracts";
import { ActivityFeed } from "./features/activity/ActivityFeed";
import { ClimateControl } from "./features/climate/ClimateControl";
import { ClimateReadout } from "./features/climate/ClimateReadout";
import type { ChartPoint } from "./features/climate/TemperatureChart";
import { TemperatureHistory } from "./features/climate/TemperatureHistory";
import {
  OperationalNotice,
  OperationsPanel,
} from "./features/operations/OperationsPanel";
import { formatDateTime } from "./shared/format";
import { overallSystemLabel, statusTone } from "./shared/status";
import { LabShell } from "./shell/LabShell";

interface DashboardProps {
  session: Session;
  onLogout: () => Promise<void>;
}

export default function Dashboard({ session, onLogout }: DashboardProps) {
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
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: getAlerts,
    refetchInterval: 30_000,
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
    alerts.dataUpdatedAt,
  );
  const systemLabel = overallSystemLabel(health.data, disconnected);
  const systemTone = statusTone(disconnected ? "degraded" : (health.data?.status ?? "unknown"));

  return (
    <LabShell
      actorId={session.actor_id}
      authEnabled={session.auth_enabled}
      systemLabel={systemLabel}
      systemTone={systemTone}
      version={health.data?.version}
      timezone={timezone}
      lastUpdated={
        lastUpdated ? formatDateTime(new Date(lastUpdated).toISOString()) : "waiting for data"
      }
      onRefresh={() => queryClient.invalidateQueries()}
      onLogout={onLogout}
    >
      {disconnected && (
        <div className="connection-banner" role="alert">
          <strong>RUBIK connection interrupted.</strong>
          <span>Last confirmed values remain visible with their original timestamps.</span>
        </div>
      )}

      <OperationalNotice alerts={alerts.data} />

      <div className="climate-hero" id="climate">
        <ClimateReadout
          health={health.data}
          latest={latest.data}
          pending={latest.isPending}
        />

        {session.controls_enabled && session.csrf_token ? (
          <ClimateControl
            key={commands.data?.items[0]?.id ?? "defaults"}
            csrfToken={session.csrf_token}
            commands={commands.data}
            degraded={health.data?.status === "degraded"}
            onCompleted={() => queryClient.invalidateQueries({ queryKey: ["commands"] })}
          />
        ) : (
          <section className="climate-control control-disabled" aria-labelledby="control-title">
            <div>
              <p className="overline">DEVICE CONTROL</p>
              <h2 id="control-title">Air conditioner</h2>
            </div>
            <p>Browser controls are disabled for this deployment.</p>
          </section>
        )}
      </div>

      <TemperatureHistory
        data={chartData}
        windowOption={windowOption}
        timezone={timezone}
        sampleCount={series.data?.sample_count ?? 0}
        pending={series.isPending}
        failed={series.isError}
        onWindowChange={setWindowOption}
      />

      <ActivityFeed
        commands={commands.data}
        pending={commands.isPending}
        failed={commands.isError}
      />

      <OperationsPanel
        health={health.data}
        alerts={alerts.data}
        alertsPending={alerts.isPending}
        alertsFailed={alerts.isError}
        disconnected={disconnected}
      />
    </LabShell>
  );
}
