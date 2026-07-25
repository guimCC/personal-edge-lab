import { z } from "zod";

const optionalTimestamp = z.string().datetime().nullable();

export const sessionSchema = z.object({
  authenticated: z.boolean(),
  auth_enabled: z.boolean(),
  controls_enabled: z.boolean(),
  actor_id: z.string().nullable().optional(),
  csrf_token: z.string().nullable().optional(),
  idle_expires_at_utc: optionalTimestamp.optional(),
  absolute_expires_at_utc: optionalTimestamp.optional(),
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
export type Health = z.infer<typeof healthSchema>;
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

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfter: number | null = null,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new Event("pel:unauthorized"));
    }
    throw new ApiError(
      `Request failed with status ${response.status}`,
      response.status,
      response.headers.get("Retry-After")
        ? Number(response.headers.get("Retry-After"))
        : null,
    );
  }
  return schema.parse(await response.json());
}

export const getSession = () => request("/api/v1/auth/session", sessionSchema);

export const login = (password: string) =>
  request("/api/v1/auth/login", sessionSchema, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });

export async function logout(csrfToken: string): Promise<void> {
  const response = await fetch("/api/v1/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: "{}",
  });
  if (!response.ok && response.status !== 401) {
    throw new ApiError(`Request failed with status ${response.status}`, response.status);
  }
}

export const getHealth = () => request("/health", healthSchema);

export async function getLatest(): Promise<Reading | null> {
  try {
    return await request("/api/v1/telemetry/latest", readingSchema);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export const getSeries = (window: WindowOption) =>
  request(
    `/api/v1/telemetry/series?window=${encodeURIComponent(window)}`,
    seriesSchema,
  );

export const getCommandHistory = () =>
  request("/api/v1/ac/history?limit=10", commandHistorySchema);

export const sendCommand = (
  command: BrowserCommand,
  idempotencyKey: string,
  csrfToken: string,
) =>
  request("/api/v1/ac/commands", commandResponseSchema, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(command),
  });
