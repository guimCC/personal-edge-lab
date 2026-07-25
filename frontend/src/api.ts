import { z } from "zod";

const optionalTimestamp = z.string().datetime().nullable();

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

export const commandHistorySchema = z.object({
  count: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  items: z.array(
    z.object({
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
    }),
  ),
});

export type Health = z.infer<typeof healthSchema>;
export type Reading = z.infer<typeof readingSchema>;
export type Series = z.infer<typeof seriesSchema>;
export type CommandHistory = z.infer<typeof commandHistorySchema>;
export type WindowOption = Series["window"];

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(`Request failed with status ${response.status}`, response.status);
  }
  return schema.parse(await response.json());
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
