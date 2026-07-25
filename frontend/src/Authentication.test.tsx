import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  emptyCommands,
  emptySeries,
  healthyAlerts,
  healthyPlatform,
  latestReading,
} from "./test/fixtures";
import { response } from "./test/mockApi";
import { installReactTestEnvironment, renderApp } from "./test/renderApp";

installReactTestEnvironment();

describe("owner authentication", () => {
  it("shows only the login shell until the owner authenticates", async () => {
    let authenticated = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/session")) {
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
      }
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
      if (url === "/health") return Promise.resolve(response(healthyPlatform));
      if (url.includes("/latest")) return Promise.resolve(response(latestReading));
      if (url.includes("/alerts")) return Promise.resolve(response(healthyAlerts));
      if (url.includes("/series")) return Promise.resolve(response(emptySeries));
      if (url.includes("/ac/history")) return Promise.resolve(response(emptyCommands));
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderApp();
    expect(await screen.findByRole("heading", { name: "Enter your lab" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Room climate" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith("/health", expect.anything());

    await userEvent.type(screen.getByLabelText("Password"), "fourteen-chars!");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Room climate" })).toBeVisible();
  });
});
