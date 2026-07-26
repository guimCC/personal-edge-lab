export const NOW = "2026-07-25T14:00:00Z";

export const healthyPlatform = {
  status: "healthy",
  version: "0.7.1",
  checked_at_utc: NOW,
  database: { status: "healthy" },
  telemetry: {
    status: "fresh",
    device_id: "node-1",
    last_received_at_utc: "2026-07-25T13:59:55Z",
    age_seconds: 5,
    stale_after_seconds: 45,
  },
  collector: {
    status: "running",
    device_id: "node-1",
    process_started_at_utc: "2026-07-25T13:00:00Z",
    heartbeat_at_utc: "2026-07-25T13:59:55Z",
    heartbeat_age_seconds: 5,
    stale_after_seconds: 45,
    stopped_at_utc: null,
    last_attempt_at_utc: "2026-07-25T13:59:55Z",
    last_success_at_utc: "2026-07-25T13:59:55Z",
    consecutive_failures: 0,
  },
  edge_node: {
    status: "reachable",
    device_id: "node-1",
    last_attempt_at_utc: "2026-07-25T13:59:55Z",
    last_success_at_utc: "2026-07-25T13:59:55Z",
    last_failure_at_utc: null,
    last_failure_category: null,
    last_failure_message: null,
  },
  alerts: {
    status: "healthy",
    active_count: 0,
    suspect_count: 0,
    latest_transition_at_utc: null,
    evaluator_last_run_at_utc: NOW,
    evaluator_age_seconds: 0,
  },
};

export const latestReading = {
  device_id: "node-1",
  sensor: "thermistor",
  received_at_utc: "2026-07-25T13:59:55Z",
  estimated_sample_at_utc: "2026-07-25T13:59:54Z",
  temperature_c: 24.5,
  raw_adc: 1700,
  age_ms: 1000,
  sample_interval_ms: 2000,
};

export const healthyAlerts = {
  device_id: "node-1",
  status: "healthy",
  evaluator_last_run_at_utc: NOW,
  evaluator_age_seconds: 0,
  count: 0,
  limit: 20,
  states: [
    {
      device_id: "node-1",
      alert_type: "edge_unavailable",
      lifecycle: "healthy",
      suspect_started_at_utc: null,
      active_incident_id: null,
      recovered_at_utc: null,
      recovery_display_until_utc: null,
      last_observed_at_utc: NOW,
      evidence_category: "reachable",
      evidence_message: "The latest collection attempt succeeded",
    },
    {
      device_id: "node-1",
      alert_type: "telemetry_stale",
      lifecycle: "healthy",
      suspect_started_at_utc: null,
      active_incident_id: null,
      recovered_at_utc: null,
      recovery_display_until_utc: null,
      last_observed_at_utc: NOW,
      evidence_category: "fresh",
      evidence_message: "Fresh telemetry is available",
    },
  ],
  incidents: [],
};

export const emptySeries = {
  device_id: "node-1",
  window: "6h",
  start_at_utc: "2026-07-25T08:00:00Z",
  end_at_utc: NOW,
  bucket_seconds: 300,
  sample_count: 0,
  items: [],
};

export const emptyCommands = { count: 0, limit: 10, items: [] };

export const openSession = {
  authenticated: false,
  auth_enabled: false,
  controls_enabled: false,
};
