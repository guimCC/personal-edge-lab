import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  healthyAlerts,
  healthyPlatform,
  NOW,
  openSession,
} from "./test/fixtures";
import { installDashboardApi, response } from "./test/mockApi";
import { installReactTestEnvironment, renderApp } from "./test/renderApp";

installReactTestEnvironment();

afterEach(() => {
  window.history.replaceState(null, "", "#climate");
});

describe("lab dashboard", () => {
  it("moves the desktop navigation state with climate sections", async () => {
    installDashboardApi();
    renderApp();

    await screen.findByRole("heading", { name: "Room climate" });
    const navigation = screen.getByRole("navigation", { name: "Workspace sections" });
    const climate = within(navigation).getByRole("link", { name: /Climate$/ });
    const activity = within(navigation).getByRole("link", { name: /Activity$/ });
    const system = within(navigation).getByRole("link", { name: /System$/ });
    expect(climate).toHaveAttribute("aria-current", "page");

    await userEvent.click(activity);
    await waitFor(() => expect(activity).toHaveAttribute("aria-current", "page"));
    expect(climate).not.toHaveAttribute("aria-current");

    await userEvent.click(system);
    await waitFor(() => expect(system).toHaveAttribute("aria-current", "page"));
    expect(activity).not.toHaveAttribute("aria-current");
  });

  it("prioritizes climate while keeping healthy operations available", async () => {
    installDashboardApi();
    renderApp();

    expect(await screen.findByRole("heading", { name: "Room climate" })).toBeVisible();
    expect(await screen.findByText("24.5")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Signal over time" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Recent activity" })).toBeVisible();
    expect(screen.getAllByText("All systems operational").length).toBeGreaterThan(0);
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("reachable")).toBeInTheDocument();
  });

  it("keeps collector and edge-node failures distinct", async () => {
    installDashboardApi({
      health: {
        ...healthyPlatform,
        status: "degraded",
        edge_node: {
          ...healthyPlatform.edge_node,
          status: "unreachable",
          last_failure_at_utc: NOW,
          last_failure_category: "timeout",
          last_failure_message: "temperature request timed out",
        },
      },
    });
    renderApp();

    expect(await screen.findByText("running")).toBeInTheDocument();
    expect(screen.getByText("unreachable")).toBeInTheDocument();
  });

  it("promotes a durable active incident above the climate module", async () => {
    installDashboardApi({
      alerts: {
        ...healthyAlerts,
        status: "alerting",
        count: 1,
        states: [
          {
            ...healthyAlerts.states[1],
            lifecycle: "alerting",
            suspect_started_at_utc: "2026-07-25T13:56:00Z",
            active_incident_id: 9,
            evidence_category: "stale",
            evidence_message: "Telemetry has remained stale",
          },
        ],
        incidents: [
          {
            id: 9,
            device_id: "node-1",
            alert_type: "telemetry_stale",
            status: "active",
            suspect_started_at_utc: "2026-07-25T13:56:00Z",
            alerting_at_utc: "2026-07-25T13:57:00Z",
            recovered_at_utc: null,
            last_observed_at_utc: NOW,
            duration_seconds: 180,
            evidence_category: "stale",
            evidence_message: "Telemetry has remained stale",
          },
        ],
      },
    });
    renderApp();

    expect(await screen.findByLabelText("Active operational incidents")).toBeVisible();
    expect(screen.getByText(/ACTIVE \/ telemetry stale/)).toBeVisible();
    expect(screen.getByText("Telemetry has remained stale")).toBeVisible();
    expect(screen.getByText(/3 minutes/)).toBeVisible();
    expect(screen.getAllByText("fresh", { exact: true }).length).toBeGreaterThan(0);
  });

  it("labels suspect evidence without presenting an active incident", async () => {
    installDashboardApi({
      alerts: {
        ...healthyAlerts,
        status: "suspect",
        states: [
          {
            ...healthyAlerts.states[1],
            lifecycle: "suspect",
            suspect_started_at_utc: "2026-07-25T13:59:30Z",
            evidence_category: "stale",
            evidence_message: "Telemetry has remained stale",
          },
        ],
      },
    });
    renderApp();

    expect(await screen.findByText(/SUSPECT \/ telemetry stale/)).toBeVisible();
    expect(screen.queryByText(/ACTIVE \/ telemetry stale/)).not.toBeInTheDocument();
  });

  it("keeps recovered history inside the secondary system disclosure", async () => {
    installDashboardApi({
      alerts: {
        ...healthyAlerts,
        status: "recovered",
        count: 1,
        states: [
          {
            ...healthyAlerts.states[1],
            lifecycle: "recovered",
            recovered_at_utc: "2026-07-25T13:59:30Z",
            recovery_display_until_utc: "2026-07-25T14:04:30Z",
          },
        ],
        incidents: [
          {
            id: 10,
            device_id: "node-1",
            alert_type: "telemetry_stale",
            status: "recovered",
            suspect_started_at_utc: "2026-07-25T13:55:00Z",
            alerting_at_utc: "2026-07-25T13:57:00Z",
            recovered_at_utc: "2026-07-25T13:59:30Z",
            last_observed_at_utc: "2026-07-25T13:59:30Z",
            duration_seconds: 150,
            evidence_category: "fresh",
            evidence_message: "Fresh telemetry is available",
          },
        ],
      },
    });
    renderApp();

    await screen.findByRole("heading", { name: "Room climate" });
    await userEvent.click(screen.getByRole("heading", { name: "System" }));
    expect(await screen.findByText(/Recovered/)).toBeVisible();
    expect(screen.queryByLabelText("Active operational incidents")).not.toBeInTheDocument();
  });

  it("makes an overdue evaluator visible as unknown", async () => {
    installDashboardApi({
      alerts: {
        ...healthyAlerts,
        status: "unknown",
        evaluator_age_seconds: 120,
      },
    });
    renderApp();

    await screen.findByRole("heading", { name: "Room climate" });
    await userEvent.click(screen.getByRole("heading", { name: "System" }));
    expect(await screen.findByText("unknown", { exact: true })).toBeVisible();
  });

  it("requests a new bounded series when the chart window changes", async () => {
    const fetchMock = installDashboardApi();
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
          ? Promise.resolve(response(openSession))
          : Promise.reject(new Error("offline")),
      ),
    );
    renderApp();

    expect(await screen.findByText(/RUBIK connection interrupted/)).toBeVisible();
    expect(screen.getByText("Unreachable")).toBeInTheDocument();
  });
});
