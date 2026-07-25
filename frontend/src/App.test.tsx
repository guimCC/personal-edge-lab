import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const NOW = "2026-07-25T14:00:00Z";

const health = {
  status: "healthy",
  version: "0.4.0",
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
};

const latest = {
  device_id: "node-1",
  sensor: "thermistor",
  received_at_utc: "2026-07-25T13:59:55Z",
  estimated_sample_at_utc: "2026-07-25T13:59:54Z",
  temperature_c: 24.5,
  raw_adc: 1700,
  age_ms: 1000,
  sample_interval_ms: 2000,
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe("dashboard", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows current temperature and distinct healthy services", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/session"))
          return Promise.resolve(
            response({
              authenticated: false,
              auth_enabled: false,
              controls_enabled: false,
            }),
          );
        if (url === "/health") return Promise.resolve(response(health));
        if (url.includes("/latest")) return Promise.resolve(response(latest));
        if (url.includes("/series"))
          return Promise.resolve(
            response({
              device_id: "node-1",
              window: "6h",
              start_at_utc: "2026-07-25T08:00:00Z",
              end_at_utc: NOW,
              bucket_seconds: 300,
              sample_count: 0,
              items: [],
            }),
          );
        return Promise.resolve(response({ count: 0, limit: 10, items: [] }));
      }),
    );

    renderApp();
    expect(await screen.findByText("24.5")).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("reachable")).toBeInTheDocument();
    expect(screen.getAllByText("fresh").length).toBeGreaterThan(0);
  });

  it("keeps service distinctions when the collector runs but ESP32 fails", async () => {
    const degraded = {
      ...health,
      status: "degraded",
      edge_node: {
        ...health.edge_node,
        status: "unreachable",
        last_failure_at_utc: NOW,
        last_failure_category: "timeout",
        last_failure_message: "temperature request timed out",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/session"))
          return Promise.resolve(
            response({
              authenticated: false,
              auth_enabled: false,
              controls_enabled: false,
            }),
          );
        if (url === "/health") return Promise.resolve(response(degraded));
        if (url.includes("/latest")) return Promise.resolve(response(latest));
        if (url.includes("/series"))
          return Promise.resolve(
            response({
              device_id: "node-1",
              window: "6h",
              start_at_utc: "2026-07-25T08:00:00Z",
              end_at_utc: NOW,
              bucket_seconds: 300,
              sample_count: 0,
              items: [],
            }),
          );
        return Promise.resolve(response({ count: 0, limit: 10, items: [] }));
      }),
    );

    renderApp();
    expect(await screen.findByText("running")).toBeInTheDocument();
    expect(screen.getByText("unreachable")).toBeInTheDocument();
  });

  it("requests a new bounded series when the chart window changes", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/session"))
        return Promise.resolve(
          response({
            authenticated: false,
            auth_enabled: false,
            controls_enabled: false,
          }),
        );
      if (url === "/health") return Promise.resolve(response(health));
      if (url.includes("/latest")) return Promise.resolve(response(latest));
      if (url.includes("/series"))
        return Promise.resolve(
          response({
            device_id: "node-1",
            window: url.includes("24h") ? "24h" : "6h",
            start_at_utc: "2026-07-24T14:00:00Z",
            end_at_utc: NOW,
            bucket_seconds: url.includes("24h") ? 900 : 300,
            sample_count: 0,
            items: [],
          }),
        );
      return Promise.resolve(response({ count: 0, limit: 10, items: [] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderApp();
    await screen.findByText("24.5");
    await userEvent.click(screen.getByRole("button", { name: "24h" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/telemetry/series?window=24h",
        expect.anything(),
      ),
    );
  });

  it("shows a clear disconnected state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        String(input).includes("/auth/session")
          ? Promise.resolve(
              response({
                authenticated: false,
                auth_enabled: false,
                controls_enabled: false,
              }),
            )
          : Promise.reject(new Error("offline")),
      ),
    );
    renderApp();
    expect(await screen.findByRole("alert")).toHaveTextContent("did not answer");
    expect(screen.getByText("Unreachable")).toBeInTheDocument();
  });

  it("shows only the login shell until the owner authenticates", async () => {
    let authenticated = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/session"))
        return Promise.resolve(
          response({
            authenticated,
            auth_enabled: true,
            controls_enabled: false,
            ...(authenticated
              ? {
                  actor_id: "owner",
                  csrf_token: "csrf",
                  idle_expires_at_utc: "2026-07-26T14:00:00Z",
                  absolute_expires_at_utc: "2026-08-01T14:00:00Z",
                }
              : {}),
          }),
        );
      if (url.includes("/auth/login") && init?.method === "POST") {
        authenticated = true;
        return Promise.resolve(
          response({
            authenticated: true,
            auth_enabled: true,
            controls_enabled: false,
            actor_id: "owner",
            csrf_token: "csrf",
            idle_expires_at_utc: "2026-07-26T14:00:00Z",
            absolute_expires_at_utc: "2026-08-01T14:00:00Z",
          }),
        );
      }
      if (url === "/health") return Promise.resolve(response(health));
      if (url.includes("/latest")) return Promise.resolve(response(latest));
      if (url.includes("/series"))
        return Promise.resolve(
          response({
            device_id: "node-1",
            window: "6h",
            start_at_utc: "2026-07-25T08:00:00Z",
            end_at_utc: NOW,
            bucket_seconds: 300,
            sample_count: 0,
            items: [],
          }),
        );
      return Promise.resolve(response({ count: 0, limit: 10, items: [] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderApp();
    expect(await screen.findByRole("heading", { name: "Owner sign in" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Room telemetry" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith("/health", expect.anything());

    await userEvent.type(screen.getByLabelText("Password"), "fourteen-chars!");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Room telemetry" })).toBeVisible();
  });

  it("requires review and one confirmation before Power Off", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/session"))
        return Promise.resolve(
          response({
            authenticated: true,
            auth_enabled: true,
            controls_enabled: true,
            actor_id: "owner",
            csrf_token: "csrf-token",
            idle_expires_at_utc: "2026-07-26T14:00:00Z",
            absolute_expires_at_utc: "2026-08-01T14:00:00Z",
          }),
        );
      if (url === "/health") return Promise.resolve(response(health));
      if (url.includes("/latest")) return Promise.resolve(response(latest));
      if (url.includes("/series"))
        return Promise.resolve(
          response({
            device_id: "node-1",
            window: "6h",
            start_at_utc: "2026-07-25T08:00:00Z",
            end_at_utc: NOW,
            bucket_seconds: 300,
            sample_count: 0,
            items: [],
          }),
        );
      if (url.includes("/ac/history"))
        return Promise.resolve(response({ count: 0, limit: 10, items: [] }));
      if (url.includes("/ac/commands") && init?.method === "POST")
        return Promise.resolve(
          response(
            {
              audit: {
                id: 7,
                device_id: "node-1",
                command_type: "power_off",
                command_payload: { power: false },
                requested_at_utc: NOW,
                completed_at_utc: NOW,
                outcome: "confirmed_success",
                http_status: 200,
                response_body: "{}",
                error_category: null,
                error_message: null,
                actor_id: "owner",
                request_source: "dashboard",
                idempotency_key: "generated-key",
              },
              replayed: false,
            },
            201,
          ),
        );
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderApp();
    await screen.findByRole("heading", { name: "Air conditioner" });
    await userEvent.click(screen.getByRole("button", { name: "Review Power Off" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Power off AC?");
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).includes("/ac/commands")),
    ).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Confirm once" }));
    expect(await screen.findByText("The ESP32 confirmed the command.")).toBeVisible();
    const calls = fetchMock.mock.calls.filter(([input]) =>
      String(input).includes("/ac/commands"),
    );
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ command_type: "power_off" });
  });
});
