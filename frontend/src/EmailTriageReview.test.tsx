import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
  email_triage_workspace_enabled: true,
  email_triage_review_enabled: true,
  actor_id: "owner",
  csrf_token: "csrf",
  idle_expires_at_utc: "2026-07-29T12:00:00Z",
  absolute_expires_at_utc: "2026-08-04T12:00:00Z",
};

const message = {
  record_id: "a".repeat(32),
  received_at_utc: "2026-07-28T11:59:00Z",
  sender: "Private Sender <sender@example.test>",
  subject: "<script>subject stays text</script>",
  label: "work",
  reason_preview: "The message concerns a work task.",
  latest_status: "succeeded",
  latest_failure_category: null,
  last_triaged_at_utc: "2026-07-28T12:00:00Z",
  model_input_truncated: true,
  source_truncated: false,
  has_recommendation: true,
};

const messageDetail = {
  summary: message,
  normalized_text: "private-body-sentinelprivate-remainder-sentinel",
  model_input: "private-body-sentinel",
  normalized_sha256: "b".repeat(64),
  model_input_sha256: "c".repeat(64),
  original_size_bytes: 3000,
  content_source: "plain_text",
  cleanup_flags: ["quoted_text_removed"],
  metadata_truncated: false,
  technical: {
    run_id: "run-review-001",
    item_ordinal: 1,
    attempt_id: 1,
    decision_sha256: "d".repeat(64),
    prompt_source: "langfuse",
    prompt_version: "1",
    profile_version: "1.0.0",
    taxonomy_version: "1.0.0",
    schema_version: "1.0.0",
    generation_parameters_version: "1.0.0",
    provider: "llama_cpp",
    model_alias: "qwen3-1.7b-q4-k-m",
    trace_id: "e".repeat(32),
    prompt_tokens: 100,
    completion_tokens: 30,
    total_tokens: 130,
    queue_wait_seconds: 0,
    provider_seconds: 10.2,
    total_seconds: 10.2,
  },
  gmail_changes: "none",
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
};

function installWorkspaceApi(enabled = true) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/auth/session")) {
      return Promise.resolve(
        response({
          ...session,
          email_triage_workspace_enabled: enabled,
          email_triage_review_enabled: enabled,
        }),
      );
    }
    if (url === "/health") return Promise.resolve(response(healthyPlatform));
    if (url.endsWith(`/email-triage/messages/${message.record_id}`)) {
      expect(init?.cache).toBe("no-store");
      return Promise.resolve(response(messageDetail));
    }
    if (url.includes("/email-triage/messages?")) {
      expect(init?.cache).toBe("no-store");
      return Promise.resolve(
        response({
          count: 1,
          limit: 20,
          status: "all",
          label: null,
          next_cursor: null,
          items: [message],
        }),
      );
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

describe("message-centric email-triage workspace", () => {
  it("shows emails first and loads stored body only when the email is opened", async () => {
    window.history.replaceState(null, "", "#email-triage");
    const fetchMock = installWorkspaceApi();
    vi.stubGlobal("fetch", fetchMock);
    const rendered = renderApp();

    expect(await screen.findByRole("heading", { name: "Email triage" })).toBeVisible();
    const mobileNavigation = screen.getByRole("navigation", {
      name: "Mobile workspace sections",
    });
    expect(
      within(mobileNavigation).getByRole("link", { name: /Email triage/ }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Gmail labels applied: none")).toBeVisible();
    expect(await screen.findByText("Recommendation · work")).toBeVisible();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith(`/messages/${message.record_id}`),
      ),
    ).toBe(false);
    expect(screen.queryByText("private-body-sentinel")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /subject stays text/ }),
    );
    expect(await screen.findByText("private-body-sentinel")).toBeVisible();
    expect(screen.getAllByText("<script>subject stays text</script>").length).toBeGreaterThan(0);
    expect(rendered.container.querySelector("script")).toBeNull();
    expect(screen.getByText(/Remaining normalized email/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Close and clear" }));
    expect(screen.queryByText("private-body-sentinel")).not.toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("keeps run evidence behind the diagnostics view and clears content on navigation", async () => {
    window.history.replaceState(null, "", "#email-triage");
    vi.stubGlobal("fetch", installWorkspaceApi());
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /subject stays text/ }),
    );
    expect(await screen.findByText("private-body-sentinel")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Diagnostics" }));
    expect(screen.queryByText("private-body-sentinel")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Diagnostics" })).toBeVisible();
    expect(await screen.findByText(/1 messages · 1 new/)).toBeVisible();

    const desktopNavigation = screen.getByRole("navigation", {
      name: "Workspace sections",
    });
    fireEvent.click(within(desktopNavigation).getByRole("link", { name: /Climate/ }));
    await waitFor(() =>
      expect(screen.queryByText("private-body-sentinel")).not.toBeInTheDocument(),
    );
  });

  it("hides the workspace when the authenticated session gate is disabled", async () => {
    window.history.replaceState(null, "", "#email-triage");
    vi.stubGlobal("fetch", installWorkspaceApi(false));
    renderApp();

    expect(await screen.findByRole("heading", { name: "Room climate" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Email triage" })).not.toBeInTheDocument();
  });
});
