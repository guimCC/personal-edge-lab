import { z } from "zod";

import {
  alertsSchema,
  commandHistorySchema,
  commandResponseSchema,
  healthSchema,
  readingSchema,
  seriesSchema,
  sessionSchema,
  triageMessageDetailSchema,
  triageMessageListSchema,
  triageFeedbackSchema,
  triageRunDetailSchema,
  triageRunListSchema,
  type BrowserCommand,
  type Reading,
  type TriageLabel,
  type TriageMessageStatusFilter,
  type TriageRunFilter,
  type WindowOption,
} from "./contracts";

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

export const getAlerts = () => request("/api/v1/alerts?status=all&limit=20", alertsSchema);

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

export const getTriageRuns = (status: TriageRunFilter, limit = 20) =>
  request(
    `/api/v1/email-triage/runs?limit=${limit}&status=${encodeURIComponent(status)}`,
    triageRunListSchema,
    { cache: "no-store" },
  );

export const getTriageRun = (runId: string) =>
  request(
    `/api/v1/email-triage/runs/${encodeURIComponent(runId)}`,
    triageRunDetailSchema,
    { cache: "no-store" },
  );

export const getTriageMessages = (
  status: TriageMessageStatusFilter,
  label: TriageLabel | "all",
  cursor: string | null = null,
  limit = 20,
) => {
  const parameters = new URLSearchParams({
    limit: String(limit),
    status,
    label,
  });
  if (cursor) parameters.set("cursor", cursor);
  return request(
    `/api/v1/email-triage/messages?${parameters.toString()}`,
    triageMessageListSchema,
    { cache: "no-store" },
  );
};

export const getTriageMessage = (recordId: string) =>
  request(
    `/api/v1/email-triage/messages/${encodeURIComponent(recordId)}`,
    triageMessageDetailSchema,
    { cache: "no-store" },
  );

export const recordTriageFeedback = (
  recordId: string,
  feedback: {
    recommendation_attempt_id: number;
    expected_version: number;
    action: "confirm" | "correct" | "dismiss";
    corrected_label: TriageLabel | null;
  },
  csrfToken: string,
) =>
  request(
    `/api/v1/email-triage/messages/${encodeURIComponent(recordId)}/feedback`,
    triageFeedbackSchema,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(feedback),
    },
  );

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
