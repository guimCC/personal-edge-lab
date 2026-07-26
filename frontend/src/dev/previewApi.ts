const NOW = new Date();
const isoSecondsAgo = (seconds: number) =>
  new Date(NOW.getTime() - seconds * 1000).toISOString();

const json = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );

export function installPreviewApi(): void {
  window.fetch = (input) => {
    const url = String(input);
    if (url.includes("/auth/session")) {
      return json({
        authenticated: true,
        auth_enabled: true,
        controls_enabled: true,
        actor_id: "owner",
        csrf_token: "preview-csrf",
        idle_expires_at_utc: isoSecondsAgo(-3600),
        absolute_expires_at_utc: isoSecondsAgo(-86400),
      });
    }
    if (url === "/health") {
      return json({
        status: "healthy",
        version: "0.7.1",
        checked_at_utc: NOW.toISOString(),
        database: { status: "healthy" },
        telemetry: {
          status: "fresh",
          device_id: "ac-controller-01",
          last_received_at_utc: isoSecondsAgo(7),
          age_seconds: 7,
          stale_after_seconds: 45,
        },
        collector: {
          status: "running",
          device_id: "ac-controller-01",
          process_started_at_utc: isoSecondsAgo(3600),
          heartbeat_at_utc: isoSecondsAgo(7),
          heartbeat_age_seconds: 7,
          stale_after_seconds: 45,
          stopped_at_utc: null,
          last_attempt_at_utc: isoSecondsAgo(7),
          last_success_at_utc: isoSecondsAgo(7),
          consecutive_failures: 0,
        },
        edge_node: {
          status: "reachable",
          device_id: "ac-controller-01",
          last_attempt_at_utc: isoSecondsAgo(7),
          last_success_at_utc: isoSecondsAgo(7),
          last_failure_at_utc: null,
          last_failure_category: null,
          last_failure_message: null,
        },
        alerts: {
          status: "healthy",
          active_count: 0,
          suspect_count: 0,
          latest_transition_at_utc: null,
          evaluator_last_run_at_utc: isoSecondsAgo(12),
          evaluator_age_seconds: 12,
        },
      });
    }
    if (url.includes("/alerts")) {
      return json({
        device_id: "ac-controller-01",
        status: "healthy",
        evaluator_last_run_at_utc: isoSecondsAgo(12),
        evaluator_age_seconds: 12,
        count: 0,
        limit: 20,
        states: [],
        incidents: [],
      });
    }
    if (url.includes("/telemetry/latest")) {
      return json({
        device_id: "ac-controller-01",
        sensor: "thermistor",
        received_at_utc: isoSecondsAgo(7),
        estimated_sample_at_utc: isoSecondsAgo(8),
        temperature_c: 25.9,
        raw_adc: 1700,
        age_ms: 900,
        sample_interval_ms: 2000,
      });
    }
    if (url.includes("/telemetry/series")) {
      const windowOption = new URL(url, location.origin).searchParams.get("window") ?? "6h";
      const points = Array.from({ length: 24 }, (_, index) => {
        const average = 24.4 + Math.sin(index / 3) * 1.2 + index * 0.04;
        const start = new Date(NOW.getTime() - (23 - index) * 15 * 60 * 1000);
        return {
          bucket_start_at_utc: start.toISOString(),
          bucket_end_at_utc: new Date(start.getTime() + 15 * 60 * 1000).toISOString(),
          sample_count: 60,
          temperature_minimum_c: average - 0.25,
          temperature_average_c: average,
          temperature_maximum_c: average + 0.3,
        };
      });
      return json({
        device_id: "ac-controller-01",
        window: windowOption,
        start_at_utc: points[0].bucket_start_at_utc,
        end_at_utc: NOW.toISOString(),
        bucket_seconds: windowOption === "1h" ? 60 : windowOption === "24h" ? 900 : 300,
        sample_count: 1440,
        items: points,
      });
    }
    if (url.includes("/ac/history")) {
      return json({
        count: 2,
        limit: 10,
        items: [
          {
            id: 12,
            device_id: "ac-controller-01",
            command_type: "set_state",
            command_payload: {
              power: true,
              temperature_c: 24,
              mode: "cool",
              fan: "auto",
              vertical_vane: "middle",
            },
            requested_at_utc: isoSecondsAgo(1800),
            completed_at_utc: isoSecondsAgo(1799),
            outcome: "confirmed_success",
            http_status: 200,
            response_body: "{}",
            error_category: null,
            error_message: null,
            actor_id: "owner",
            request_source: "dashboard",
            idempotency_key: "preview-12",
          },
          {
            id: 11,
            device_id: "ac-controller-01",
            command_type: "power_off",
            command_payload: { power: false },
            requested_at_utc: isoSecondsAgo(7200),
            completed_at_utc: isoSecondsAgo(7199),
            outcome: "confirmed_success",
            http_status: 200,
            response_body: "{}",
            error_category: null,
            error_message: null,
            actor_id: "owner",
            request_source: "dashboard",
            idempotency_key: "preview-11",
          },
        ],
      });
    }
    return json({ detail: "preview endpoint unavailable" }, 404);
  };
}
