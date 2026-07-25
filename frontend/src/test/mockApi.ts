import { vi } from "vitest";

import {
  emptyCommands,
  emptySeries,
  healthyAlerts,
  healthyPlatform,
  latestReading,
  openSession,
} from "./fixtures";

export interface ApiFixtureOverrides {
  session?: unknown;
  health?: unknown;
  latest?: unknown;
  alerts?: unknown;
  series?: unknown;
  commands?: unknown;
}

export function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function installDashboardApi(overrides: ApiFixtureOverrides = {}) {
  const fixtures = {
    session: openSession,
    health: healthyPlatform,
    latest: latestReading,
    alerts: healthyAlerts,
    series: emptySeries,
    commands: emptyCommands,
    ...overrides,
  };
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/auth/session")) return Promise.resolve(response(fixtures.session));
    if (url === "/health") return Promise.resolve(response(fixtures.health));
    if (url.includes("/latest")) return Promise.resolve(response(fixtures.latest));
    if (url.includes("/alerts")) return Promise.resolve(response(fixtures.alerts));
    if (url.includes("/series")) {
      const selectedWindow = url.includes("24h")
        ? "24h"
        : url.includes("1h")
          ? "1h"
          : "6h";
      return Promise.resolve(
        response({ ...(fixtures.series as object), window: selectedWindow }),
      );
    }
    if (url.includes("/ac/history")) return Promise.resolve(response(fixtures.commands));
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
