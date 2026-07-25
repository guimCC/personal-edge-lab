import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  emptyCommands,
  emptySeries,
  healthyAlerts,
  healthyPlatform,
  latestReading,
  NOW,
} from "./test/fixtures";
import { response } from "./test/mockApi";
import { installReactTestEnvironment, renderApp } from "./test/renderApp";

installReactTestEnvironment();

describe("climate control", () => {
  it("requires review and one confirmation before Power Off", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/session")) {
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
      }
      if (url === "/health") return Promise.resolve(response(healthyPlatform));
      if (url.includes("/latest")) return Promise.resolve(response(latestReading));
      if (url.includes("/alerts")) return Promise.resolve(response(healthyAlerts));
      if (url.includes("/series")) return Promise.resolve(response(emptySeries));
      if (url.includes("/ac/history")) return Promise.resolve(response(emptyCommands));
      if (url.includes("/ac/commands") && init?.method === "POST") {
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
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderApp();
    await screen.findByRole("heading", { name: "Air conditioner" });
    await userEvent.click(screen.getByRole("button", { name: "Power off" }));
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
