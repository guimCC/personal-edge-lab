import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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

const session = {
  authenticated: true,
  auth_enabled: true,
  controls_enabled: false,
  email_triage_review_enabled: true,
  actor_id: "owner",
  csrf_token: "csrf",
  idle_expires_at_utc: "2026-07-29T12:00:00Z",
  absolute_expires_at_utc: "2026-08-04T12:00:00Z",
};

const run = {
  run_id: "run-review-001",
  status: "completed_with_results",
  query_sha256: "f".repeat(64),
  requested_limit: 1,
  force_new_attempt: true,
  requested_at_utc: "2026-07-28T12:00:00Z",
  completed_at_utc: "2026-07-28T12:01:00Z",
  document_count: 1,
  retrieval_failure_count: 0,
  succeeded_count: 1,
  reused_count: 0,
  failed_count: 0,
  interrupted_count: 0,
};

const item = {
  ordinal: 1,
  message_fingerprint: "a".repeat(64),
  received_at_utc: "2026-07-28T11:59:00Z",
  status: "succeeded",
  label: "work",
  decision_sha256: "b".repeat(64),
  reason_chars: 42,
  failure_category: null,
  prompt_source: "langfuse",
  prompt_version: "1",
  profile_version: "1.0.0",
  model_alias: "qwen3-1.7b-q4-k-m",
  trace_id: "c".repeat(32),
  queue_wait_seconds: 0,
  provider_seconds: 10.2,
  total_seconds: 10.2,
  prompt_tokens: 100,
  completion_tokens: 30,
  total_tokens: 130,
  attempt_id: 1,
  review_available: true,
};

const privateContent = {
  run_id: run.run_id,
  ordinal: 1,
  message_fingerprint: item.message_fingerprint,
  sender: "Private Sender <sender@example.test>",
  subject: "<script>subject stays text</script>",
  model_input: "private-body-sentinel",
  normalized_remainder: "private-remainder-sentinel",
  normalized_chars: 48,
  model_input_chars: 21,
  content_source: "plain_text",
  cleanup_flags: ["quoted_text_removed"],
  source_truncated: false,
  model_input_truncated: true,
  metadata_truncated: false,
  identity_verified: true,
  api_call_count: 1,
  elapsed_seconds: 0.5,
  gmail_changes: "none",
};

function installReviewApi(enabled = true) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/auth/session")) {
      return Promise.resolve(
        response({ ...session, email_triage_review_enabled: enabled }),
      );
    }
    if (url === "/health") return Promise.resolve(response(healthyPlatform));
    if (url.includes("/email-triage/runs/run-review-001/items/1/review")) {
      expect(init?.cache).toBe("no-store");
      return Promise.resolve(response(privateContent));
    }
    if (url.endsWith("/email-triage/runs/run-review-001")) {
      return Promise.resolve(response({ run, items: [item], gmail_changes: "none" }));
    }
    if (url.includes("/email-triage/runs?")) {
      return Promise.resolve(
        response({ count: 1, limit: 20, status: "all", items: [run] }),
      );
    }
    if (url.includes("/latest")) return Promise.resolve(response(latestReading));
    if (url.includes("/alerts")) return Promise.resolve(response(healthyAlerts));
    if (url.includes("/series")) return Promise.resolve(response(emptySeries));
    if (url.includes("/ac/history")) return Promise.resolve(response(emptyCommands));
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
}

afterEach(() => {
  window.history.replaceState(null, "", "#climate");
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("protected email-triage workspace", () => {
  it("loads private content only after an explicit action and clears it on close", async () => {
    window.history.replaceState(null, "", "#email-triage");
    const fetchMock = installReviewApi();
    vi.stubGlobal("fetch", fetchMock);
    const rendered = renderApp();

    expect(await screen.findByRole("heading", { name: "Email triage" })).toBeVisible();
    expect(screen.getByText("Gmail labels applied: none")).toBeVisible();
    expect(await screen.findByText("Recommendation · work")).toBeVisible();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/items/1/review")),
    ).toBe(false);
    expect(screen.queryByText("private-body-sentinel")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load private email content" }));
    expect(await screen.findByText("private-body-sentinel")).toBeVisible();
    expect(screen.getByText("<script>subject stays text</script>")).toBeVisible();
    expect(rendered.container.querySelector("script")).toBeNull();
    expect(screen.getByText(/Normalized remainder/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Close and clear" }));
    expect(screen.queryByText("private-body-sentinel")).not.toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("clears private content when leaving the workspace", async () => {
    window.history.replaceState(null, "", "#email-triage");
    vi.stubGlobal("fetch", installReviewApi());
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "Load private email content" }),
    );
    expect(await screen.findByText("private-body-sentinel")).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: /Climate/ }));

    await waitFor(() =>
      expect(screen.queryByText("private-body-sentinel")).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole("heading", { name: "Room climate" })).toBeVisible();
  });

  it("hides the workspace when the authenticated session gate is disabled", async () => {
    window.history.replaceState(null, "", "#email-triage");
    vi.stubGlobal("fetch", installReviewApi(false));
    renderApp();

    expect(await screen.findByRole("heading", { name: "Room climate" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Email triage" })).not.toBeInTheDocument();
  });
});
