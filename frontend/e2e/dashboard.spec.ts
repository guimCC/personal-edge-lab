import { expect, test } from "@playwright/test";

const NOW = "2026-07-25T14:00:00Z";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({
      json: {
        authenticated: false,
        auth_enabled: false,
        controls_enabled: false,
      },
    }),
  );
  await page.route("**/health", async (route) => {
    await route.fulfill({
      json: {
        status: "healthy",
        version: "0.7.1",
        checked_at_utc: NOW,
        database: { status: "healthy" },
        telemetry: {
          status: "fresh",
          device_id: "ac-controller-01",
          last_received_at_utc: "2026-07-25T13:59:55Z",
          age_seconds: 5,
          stale_after_seconds: 45,
        },
        collector: {
          status: "running",
          device_id: "ac-controller-01",
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
          device_id: "ac-controller-01",
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
      },
    });
  });
  await page.route("**/api/v1/alerts?status=all&limit=20", (route) =>
    route.fulfill({
      json: {
        device_id: "ac-controller-01",
        status: "healthy",
        evaluator_last_run_at_utc: NOW,
        evaluator_age_seconds: 0,
        count: 0,
        limit: 20,
        states: [],
        incidents: [],
      },
    }),
  );
  await page.route("**/api/v1/telemetry/latest", (route) =>
    route.fulfill({
      json: {
        device_id: "ac-controller-01",
        sensor: "thermistor",
        received_at_utc: "2026-07-25T13:59:55Z",
        estimated_sample_at_utc: "2026-07-25T13:59:54Z",
        temperature_c: 24.5,
        raw_adc: 1700,
        age_ms: 1000,
        sample_interval_ms: 2000,
      },
    }),
  );
  await page.route("**/api/v1/telemetry/series?window=*", async (route) => {
    const window = new URL(route.request().url()).searchParams.get("window") ?? "6h";
    await route.fulfill({
      json: {
        device_id: "ac-controller-01",
        window,
        start_at_utc: "2026-07-24T14:00:00Z",
        end_at_utc: NOW,
        bucket_seconds: window === "24h" ? 900 : window === "1h" ? 60 : 300,
        sample_count: 0,
        items: [],
      },
    });
  });
  await page.route("**/api/v1/ac/history?limit=10", (route) =>
    route.fulfill({ json: { count: 0, limit: 10, items: [] } }),
  );
});

test("renders the phone-first health overview without horizontal overflow", async (
  { page },
  testInfo,
) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Room climate" })).toBeVisible();
  await expect(page.getByText("24.5")).toBeVisible();
  if (testInfo.project.name === "phone") {
    await expect(page.getByLabel("All systems operational")).toBeVisible();
  } else {
    await expect(
      page.locator(".rail-status").getByText("All systems operational"),
    ).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Recent activity" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "System" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("switches to the bounded 24-hour chart window", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "24h" }).click();
  await expect(page.getByRole("button", { name: "24h" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});
