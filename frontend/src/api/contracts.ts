import { z } from "zod";

const optionalTimestamp = z.string().datetime().nullable();

export const sessionSchema = z.object({
  authenticated: z.boolean(),
  auth_enabled: z.boolean(),
  controls_enabled: z.boolean(),
  email_triage_workspace_enabled: z.boolean().default(false),
  email_triage_review_enabled: z.boolean().default(false),
  actor_id: z.string().nullable().optional(),
  csrf_token: z.string().nullable().optional(),
  idle_expires_at_utc: optionalTimestamp.optional(),
  absolute_expires_at_utc: optionalTimestamp.optional(),
});

export const triageRunFilterSchema = z.enum([
  "all",
  "completed",
  "issues",
  "interrupted",
]);

export const triageRunSummarySchema = z.object({
  run_id: z.string(),
  status: z.string(),
  query_sha256: z.string(),
  requested_limit: z.number().int().positive(),
  force_new_attempt: z.boolean(),
  requested_at_utc: z.string().datetime(),
  completed_at_utc: optionalTimestamp,
  document_count: z.number().int().nonnegative(),
  retrieval_failure_count: z.number().int().nonnegative(),
  succeeded_count: z.number().int().nonnegative(),
  reused_count: z.number().int().nonnegative(),
  failed_count: z.number().int().nonnegative(),
  interrupted_count: z.number().int().nonnegative(),
  query_text: z.string().nullable().optional(),
});

export const triageRunListSchema = z.object({
  count: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  status: triageRunFilterSchema,
  items: z.array(triageRunSummarySchema),
});

export const triageRunItemSchema = z.object({
  ordinal: z.number().int().positive(),
  message_fingerprint: z.string(),
  received_at_utc: optionalTimestamp,
  status: z.string(),
  label: z.string().nullable(),
  decision_sha256: z.string().nullable(),
  reason_chars: z.number().int().nonnegative().nullable(),
  failure_category: z.string().nullable(),
  prompt_source: z.string().nullable(),
  prompt_version: z.string().nullable(),
  profile_version: z.string().nullable(),
  model_alias: z.string().nullable(),
  trace_id: z.string().nullable(),
  queue_wait_seconds: z.number().nonnegative().nullable(),
  provider_seconds: z.number().nonnegative().nullable(),
  total_seconds: z.number().nonnegative().nullable(),
  prompt_tokens: z.number().int().nonnegative().nullable(),
  completion_tokens: z.number().int().nonnegative().nullable(),
  total_tokens: z.number().int().nonnegative().nullable(),
  attempt_id: z.number().int().positive().nullable(),
});

export const triageRunDetailSchema = z.object({
  run: triageRunSummarySchema,
  items: z.array(triageRunItemSchema),
  gmail_changes: z.literal("none"),
});

export const triageMessageStatusFilterSchema = z.enum([
  "all",
  "recommendations",
  "issues",
]);

export const triageLabelSchema = z.enum([
  "work",
  "billing",
  "notification",
  "newsletter",
  "personal",
  "other",
]);

export const triageMessageSummarySchema = z.object({
  record_id: z.string(),
  received_at_utc: z.string().datetime(),
  sender: z.string(),
  subject: z.string(),
  label: triageLabelSchema.nullable(),
  reason_preview: z.string().nullable(),
  latest_status: z.string(),
  latest_failure_category: z.string().nullable(),
  last_triaged_at_utc: z.string().datetime(),
  model_input_truncated: z.boolean(),
  source_truncated: z.boolean(),
  has_recommendation: z.boolean(),
});

export const triageMessageListSchema = z.object({
  count: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  status: triageMessageStatusFilterSchema,
  label: triageLabelSchema.nullable(),
  next_cursor: z.string().nullable(),
  items: z.array(triageMessageSummarySchema),
});

export const triageMessageTechnicalSchema = z.object({
  run_id: z.string(),
  item_ordinal: z.number().int().positive(),
  attempt_id: z.number().int().positive().nullable(),
  decision_sha256: z.string().nullable(),
  prompt_source: z.string().nullable(),
  prompt_version: z.string().nullable(),
  profile_version: z.string().nullable(),
  taxonomy_version: z.string().nullable(),
  schema_version: z.string().nullable(),
  generation_parameters_version: z.string().nullable(),
  provider: z.string().nullable(),
  model_alias: z.string().nullable(),
  trace_id: z.string().nullable(),
  prompt_tokens: z.number().int().nonnegative().nullable(),
  completion_tokens: z.number().int().nonnegative().nullable(),
  total_tokens: z.number().int().nonnegative().nullable(),
  queue_wait_seconds: z.number().nonnegative().nullable(),
  provider_seconds: z.number().nonnegative().nullable(),
  total_seconds: z.number().nonnegative().nullable(),
});

export const triageMessageDetailSchema = z.object({
  summary: triageMessageSummarySchema,
  normalized_text: z.string(),
  model_input: z.string(),
  normalized_sha256: z.string(),
  model_input_sha256: z.string(),
  original_size_bytes: z.number().int().nonnegative(),
  content_source: z.string(),
  cleanup_flags: z.array(z.string()),
  metadata_truncated: z.boolean(),
  technical: triageMessageTechnicalSchema,
  gmail_changes: z.literal("none"),
});

export const healthSchema = z.object({
  status: z.enum(["healthy", "degraded"]),
  version: z.string(),
  checked_at_utc: z.string().datetime(),
  database: z.object({ status: z.literal("healthy") }),
  telemetry: z.object({
    status: z.enum(["fresh", "stale", "no_data"]),
    device_id: z.string(),
    last_received_at_utc: optionalTimestamp,
    age_seconds: z.number().nullable(),
    stale_after_seconds: z.number(),
  }),
  collector: z.object({
    status: z.enum(["running", "stopped", "stale", "no_data"]),
    device_id: z.string(),
    process_started_at_utc: optionalTimestamp,
    heartbeat_at_utc: optionalTimestamp,
    heartbeat_age_seconds: z.number().nullable(),
    stale_after_seconds: z.number(),
    stopped_at_utc: optionalTimestamp,
    last_attempt_at_utc: optionalTimestamp,
    last_success_at_utc: optionalTimestamp,
    consecutive_failures: z.number().int().nonnegative(),
  }),
  edge_node: z.object({
    status: z.enum(["reachable", "unreachable", "unknown"]),
    device_id: z.string(),
    last_attempt_at_utc: optionalTimestamp,
    last_success_at_utc: optionalTimestamp,
    last_failure_at_utc: optionalTimestamp,
    last_failure_category: z.string().nullable(),
    last_failure_message: z.string().nullable(),
  }),
  alerts: z.object({
    status: z.enum(["healthy", "suspect", "alerting", "recovered", "unknown"]),
    active_count: z.number().int().nonnegative(),
    suspect_count: z.number().int().nonnegative(),
    latest_transition_at_utc: optionalTimestamp,
    evaluator_last_run_at_utc: optionalTimestamp,
    evaluator_age_seconds: z.number().nullable(),
  }),
});

export const alertStateSchema = z.object({
  device_id: z.string(),
  alert_type: z.enum(["telemetry_stale", "edge_unavailable"]),
  lifecycle: z.enum(["healthy", "suspect", "alerting", "recovered"]),
  suspect_started_at_utc: optionalTimestamp,
  active_incident_id: z.number().int().nullable(),
  recovered_at_utc: optionalTimestamp,
  recovery_display_until_utc: optionalTimestamp,
  last_observed_at_utc: z.string().datetime(),
  evidence_category: z.string(),
  evidence_message: z.string(),
});

export const alertIncidentSchema = z.object({
  id: z.number().int().positive(),
  device_id: z.string(),
  alert_type: z.enum(["telemetry_stale", "edge_unavailable"]),
  status: z.enum(["active", "recovered"]),
  suspect_started_at_utc: z.string().datetime(),
  alerting_at_utc: z.string().datetime(),
  recovered_at_utc: optionalTimestamp,
  last_observed_at_utc: z.string().datetime(),
  duration_seconds: z.number().nonnegative(),
  evidence_category: z.string(),
  evidence_message: z.string(),
});

export const alertsSchema = z.object({
  device_id: z.string(),
  status: z.enum(["healthy", "suspect", "alerting", "recovered", "unknown"]),
  evaluator_last_run_at_utc: optionalTimestamp,
  evaluator_age_seconds: z.number().nullable(),
  count: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  states: z.array(alertStateSchema),
  incidents: z.array(alertIncidentSchema),
});

export const readingSchema = z.object({
  device_id: z.string(),
  sensor: z.string(),
  received_at_utc: z.string().datetime(),
  estimated_sample_at_utc: z.string().datetime(),
  temperature_c: z.number(),
  raw_adc: z.number().int(),
  age_ms: z.number().int(),
  sample_interval_ms: z.number().int(),
});

export const seriesSchema = z.object({
  device_id: z.string(),
  window: z.enum(["1h", "6h", "24h"]),
  start_at_utc: z.string().datetime(),
  end_at_utc: z.string().datetime(),
  bucket_seconds: z.number().int().positive(),
  sample_count: z.number().int().nonnegative(),
  items: z.array(
    z.object({
      bucket_start_at_utc: z.string().datetime(),
      bucket_end_at_utc: z.string().datetime(),
      sample_count: z.number().int().nonnegative(),
      temperature_minimum_c: z.number().nullable(),
      temperature_average_c: z.number().nullable(),
      temperature_maximum_c: z.number().nullable(),
    }),
  ),
});

export const commandAuditSchema = z.object({
  id: z.number().int(),
  device_id: z.string(),
  command_type: z.string(),
  command_payload: z.record(z.string(), z.unknown()),
  requested_at_utc: z.string().datetime(),
  completed_at_utc: optionalTimestamp,
  outcome: z.string(),
  http_status: z.number().int().nullable(),
  response_body: z.string().nullable(),
  error_category: z.string().nullable(),
  error_message: z.string().nullable(),
  actor_id: z.string().nullable(),
  request_source: z.string(),
  idempotency_key: z.string().nullable(),
});

export const commandHistorySchema = z.object({
  count: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  items: z.array(commandAuditSchema),
});

export const commandResponseSchema = z.object({
  audit: commandAuditSchema,
  replayed: z.boolean(),
});

export type Session = z.infer<typeof sessionSchema>;
export type TriageRunFilter = z.infer<typeof triageRunFilterSchema>;
export type TriageRunSummary = z.infer<typeof triageRunSummarySchema>;
export type TriageRunList = z.infer<typeof triageRunListSchema>;
export type TriageRunItem = z.infer<typeof triageRunItemSchema>;
export type TriageRunDetail = z.infer<typeof triageRunDetailSchema>;
export type TriageMessageStatusFilter = z.infer<typeof triageMessageStatusFilterSchema>;
export type TriageLabel = z.infer<typeof triageLabelSchema>;
export type TriageMessageSummary = z.infer<typeof triageMessageSummarySchema>;
export type TriageMessageList = z.infer<typeof triageMessageListSchema>;
export type TriageMessageDetail = z.infer<typeof triageMessageDetailSchema>;
export type Health = z.infer<typeof healthSchema>;
export type Alerts = z.infer<typeof alertsSchema>;
export type Reading = z.infer<typeof readingSchema>;
export type Series = z.infer<typeof seriesSchema>;
export type CommandHistory = z.infer<typeof commandHistorySchema>;
export type CommandResponse = z.infer<typeof commandResponseSchema>;
export type WindowOption = Series["window"];
export type Fan = "auto" | "low" | "medium" | "high" | "max";
export type Vane = "auto" | "highest" | "high" | "middle" | "low" | "lowest" | "swing";

export type BrowserCommand =
  | {
      command_type: "set_state";
      state: {
        power: true;
        temperature_c: number;
        mode: "cool";
        fan: Fan;
        vertical_vane: Vane;
      };
    }
  | { command_type: "power_off" };
