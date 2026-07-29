import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  getTriageMessage,
  getTriageMessages,
  getTriageBackfills,
  getTriageRun,
  getTriageRuns,
  recordTriageFeedback,
} from "../../api/client";
import type {
  TriageLabel,
  TriageMessageStatusFilter,
  TriageRunFilter,
} from "../../api/contracts";
import { formatDateTime } from "../../shared/format";

type WorkspaceView = "emails" | "diagnostics";
type DiagnosticItemFilter = "recommendations" | "reused" | "failures";

const LABELS: Array<TriageLabel | "all"> = [
  "all",
  "mckinsey",
  "education",
  "job",
  "personal",
  "admin",
  "notification",
  "newsletter",
  "slop",
  "other",
];
const CURRENT_LABELS: TriageLabel[] = LABELS.filter(
  (label): label is TriageLabel =>
    label !== "all" && label !== "work" && label !== "billing",
);

interface EmailTriageWorkspaceProps {
  feedbackEnabled: boolean;
  csrfToken: string | null;
}

function timing(value: number | null): string {
  return value == null ? "unavailable" : `${value.toFixed(3)}s`;
}

function shortFingerprint(value: string | null): string {
  return value ? value.slice(0, 16) : "unavailable";
}

export function EmailTriageWorkspace({
  feedbackEnabled,
  csrfToken,
}: EmailTriageWorkspaceProps) {
  const queryClient = useQueryClient();
  const [view, setView] = useState<WorkspaceView>("emails");
  const [statusFilter, setStatusFilter] = useState<TriageMessageStatusFilter>("all");
  const [labelFilter, setLabelFilter] = useState<TriageLabel | "all">("all");
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [pendingDetailHeight, setPendingDetailHeight] = useState<number | null>(null);
  const [correctionLabel, setCorrectionLabel] = useState<TriageLabel>("other");
  const messageListRef = useRef<HTMLElement | null>(null);
  const messageDetailRef = useRef<HTMLElement | null>(null);
  const pendingScrollRef = useRef<{
    listScrollTop: number;
    windowScrollX: number;
    windowScrollY: number;
  } | null>(null);

  const messages = useInfiniteQuery({
    queryKey: ["email-triage-messages", statusFilter, labelFilter],
    queryFn: ({ pageParam }) =>
      getTriageMessages(statusFilter, labelFilter, pageParam, 20),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const messageItems = useMemo(
    () => messages.data?.pages.flatMap((page) => page.items) ?? [],
    [messages.data],
  );
  const selectedId = selectedRecordId;
  const detail = useQuery({
    queryKey: ["email-triage-message", selectedId],
    queryFn: () => getTriageMessage(selectedId ?? ""),
    enabled: view === "emails" && selectedId !== null,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  const feedback = useMutation({
    mutationFn: ({
      action,
      correctedLabel,
    }: {
      action: "confirm" | "correct" | "dismiss";
      correctedLabel: TriageLabel | null;
    }) => {
      const current = detail.data;
      const attemptId = current?.technical.attempt_id;
      if (!current || attemptId == null || !csrfToken) {
        throw new Error("Feedback is unavailable");
      }
      return recordTriageFeedback(
        current.summary.record_id,
        {
          recommendation_attempt_id: attemptId,
          expected_version: current.summary.feedback_version,
          action,
          corrected_label: correctedLabel,
        },
        csrfToken,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["email-triage-messages"] }),
        queryClient.invalidateQueries({
          queryKey: ["email-triage-message", selectedId],
        }),
      ]);
    },
  });

  const clearPrivateDetail = () => {
    setPendingDetailHeight(null);
    pendingScrollRef.current = null;
    setSelectedRecordId(null);
    queryClient.removeQueries({ queryKey: ["email-triage-message"] });
  };

  useLayoutEffect(() => {
    const pendingScroll = pendingScrollRef.current;
    if (!pendingScroll) {
      return;
    }
    if (messageListRef.current) {
      messageListRef.current.scrollTop = pendingScroll.listScrollTop;
    }
    if (
      window.scrollX !== pendingScroll.windowScrollX ||
      window.scrollY !== pendingScroll.windowScrollY
    ) {
      window.scrollTo(pendingScroll.windowScrollX, pendingScroll.windowScrollY);
    }
    pendingScrollRef.current = null;
  }, [selectedRecordId]);

  useEffect(
    () => () => {
      queryClient.removeQueries({ queryKey: ["email-triage-message"] });
    },
    [queryClient],
  );

  const changeView = (nextView: WorkspaceView) => {
    clearPrivateDetail();
    setView(nextView);
  };

  const selectMessage = (recordId: string) => {
    if (recordId === selectedRecordId) {
      return;
    }
    pendingScrollRef.current = {
      listScrollTop: messageListRef.current?.scrollTop ?? 0,
      windowScrollX: window.scrollX,
      windowScrollY: window.scrollY,
    };
    setPendingDetailHeight(
      messageDetailRef.current
        ? Math.ceil(messageDetailRef.current.getBoundingClientRect().height)
        : null,
    );
    queryClient.removeQueries({ queryKey: ["email-triage-message"] });
    setSelectedRecordId(recordId);
  };

  return (
    <section className="triage-workspace" aria-labelledby="triage-workspace-title">
      <header className="triage-heading">
        <div>
          <p className="overline">PERSONAL EMAIL WORKSPACE</p>
          <h1 id="triage-workspace-title">Email triage</h1>
          <p>See the emails that entered triage and the latest recommendation for each one.</p>
        </div>
        <div className="triage-safety" role="status">
          <strong>Gmail labels applied: none</strong>
          <span>Read-only · stored locally on RUBIK</span>
        </div>
      </header>

      <nav className="triage-view-tabs" aria-label="Email triage views">
        <button
          className={view === "emails" ? "is-selected" : undefined}
          onClick={() => changeView("emails")}
          type="button"
        >
          Emails
        </button>
        <button
          className={view === "diagnostics" ? "is-selected" : undefined}
          onClick={() => changeView("diagnostics")}
          type="button"
        >
          Diagnostics
        </button>
      </nav>

      {view === "emails" ? (
        <>
          <div className="triage-message-filters" aria-label="Email filters">
            <div className="triage-filters">
              {(["all", "recommendations", "issues"] as const).map((value) => (
                <button
                  className={statusFilter === value ? "is-selected" : undefined}
                  key={value}
                  onClick={() => {
                    clearPrivateDetail();
                    setStatusFilter(value);
                  }}
                  type="button"
                >
                  {value}
                </button>
              ))}
            </div>
            <label>
              Label
              <select
                aria-label="Filter by label"
                onChange={(event) => {
                  clearPrivateDetail();
                  setLabelFilter(event.target.value as TriageLabel | "all");
                }}
                value={labelFilter}
              >
                {LABELS.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="triage-message-layout">
            <section
              className="triage-message-list"
              aria-label="Triaged emails"
              ref={messageListRef}
            >
              <div className="triage-section-title">
                <h2>Recent emails</h2>
                <span>{messageItems.length} shown</span>
              </div>
              {messages.isPending && <p className="triage-muted">Loading emails…</p>}
              {messages.isError && <p role="alert">Triaged emails are unavailable.</p>}
              {!messages.isPending && messageItems.length === 0 && (
                <p className="triage-muted">No triaged emails match this view.</p>
              )}
              {messageItems.map((message) => (
                <button
                  className={selectedId === message.record_id ? "is-selected" : undefined}
                  key={message.record_id}
                  onClick={() => selectMessage(message.record_id)}
                  type="button"
                >
                  <span className="triage-message-meta">
                    <strong>{message.sender}</strong>
                    <time dateTime={message.received_at_utc}>
                      {formatDateTime(message.received_at_utc)}
                    </time>
                  </span>
                  <span className="triage-message-subject">
                    {message.subject || "(no subject)"}
                  </span>
                  <span className="triage-message-recommendation">
                    {message.label ? (
                      <mark>
                        {message.decision_source === "rule" ? "Rule" : "AI"} ·{" "}
                        {message.label}
                      </mark>
                    ) : (
                      <em>No recommendation</em>
                    )}
                    {message.latest_failure_category && (
                      <em className="triage-issue">
                        Latest attempt: {message.latest_failure_category}
                      </em>
                    )}
                  </span>
                  {message.reason_preview && (
                    <span className="triage-message-reason">{message.reason_preview}</span>
                  )}
                </button>
              ))}
              {messages.hasNextPage && (
                <button
                  className="triage-load-more"
                  disabled={messages.isFetchingNextPage}
                  onClick={() => messages.fetchNextPage()}
                  type="button"
                >
                  {messages.isFetchingNextPage ? "Loading…" : "Load more emails"}
                </button>
              )}
            </section>

            <section
              className="triage-message-detail"
              aria-label="Selected email"
              ref={messageDetailRef}
              style={
                detail.isPending && pendingDetailHeight
                  ? { minHeight: pendingDetailHeight }
                  : undefined
              }
            >
              {!selectedId && <p className="triage-muted">Select an email to inspect it.</p>}
              {detail.isPending && selectedId && <p className="triage-muted">Loading email…</p>}
              {detail.isError && <p role="alert">This email is unavailable.</p>}
              {detail.data && (
                <article>
                  <header>
                    <div>
                      <p className="overline">TRIAGED EMAIL</p>
                      <h2>{detail.data.summary.subject || "(no subject)"}</h2>
                      <p>
                        {detail.data.summary.sender} ·{" "}
                        {formatDateTime(detail.data.summary.received_at_utc)}
                      </p>
                    </div>
                    <button type="button" onClick={clearPrivateDetail}>
                      Close and clear
                    </button>
                  </header>

                  <section className="triage-decision" aria-label="Recommendation">
                    <span>Recommendation</span>
                    <strong>{detail.data.summary.label ?? "Unavailable"}</strong>
                    <p>
                      {detail.data.summary.reason_preview ??
                        (detail.data.summary.decision_source === "rule"
                          ? "Matched a private deterministic sender rule."
                          : "The latest attempt did not produce a recommendation.")}
                    </p>
                    {detail.data.summary.latest_failure_category && (
                      <p className="triage-failure">
                        Latest processing issue:{" "}
                        {detail.data.summary.latest_failure_category}
                      </p>
                    )}
                    {detail.data.summary.latest_feedback && (
                      <p className="triage-feedback-state">
                        Owner feedback:{" "}
                        <strong>
                          {detail.data.summary.latest_feedback.action === "dismiss"
                            ? "dismissed"
                            : detail.data.summary.latest_feedback.expected_label}
                        </strong>
                        {" · "}
                        {detail.data.summary.latest_feedback.sync_status === "synced"
                          ? "linked to Langfuse"
                          : "Langfuse sync pending"}
                      </p>
                    )}
                    {feedbackEnabled &&
                      csrfToken &&
                      detail.data.summary.label &&
                      detail.data.technical.attempt_id && (
                        <div className="triage-feedback" aria-label="Owner feedback">
                          <div className="triage-feedback-actions">
                            <button
                              disabled={
                                feedback.isPending ||
                                detail.data.summary.label === "work" ||
                                detail.data.summary.label === "billing"
                              }
                              onClick={() =>
                                feedback.mutate({
                                  action: "confirm",
                                  correctedLabel: null,
                                })
                              }
                              type="button"
                            >
                              Confirm
                            </button>
                            <button
                              disabled={feedback.isPending}
                              onClick={() =>
                                feedback.mutate({
                                  action: "dismiss",
                                  correctedLabel: null,
                                })
                              }
                              type="button"
                            >
                              Dismiss
                            </button>
                          </div>
                          <label>
                            Correct label
                            <select
                              aria-label="Correct recommendation label"
                              disabled={feedback.isPending}
                              onChange={(event) =>
                                setCorrectionLabel(event.target.value as TriageLabel)
                              }
                              value={correctionLabel}
                            >
                              {CURRENT_LABELS.map((label) => (
                                <option key={label} value={label}>
                                  {label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <button
                            disabled={
                              feedback.isPending ||
                              correctionLabel === detail.data.summary.label
                            }
                            onClick={() =>
                              feedback.mutate({
                                action: "correct",
                                correctedLabel: correctionLabel,
                              })
                            }
                            type="button"
                          >
                            Save correction
                          </button>
                          {feedback.isError && (
                            <p role="alert">
                              Feedback could not be saved. Refresh this email and try again.
                            </p>
                          )}
                        </div>
                      )}
                  </section>

                  <section className="triage-content">
                    <h3>
                      {detail.data.summary.decision_source === "rule"
                        ? "Stored normalized content"
                        : "Content seen by the model"}
                    </h3>
                    <pre>{detail.data.model_input}</pre>
                    {detail.data.normalized_text.length > detail.data.model_input.length && (
                      <details>
                        <summary>
                          Remaining normalized email (
                          {detail.data.normalized_text.length - detail.data.model_input.length}{" "}
                          characters)
                        </summary>
                        <pre>
                          {detail.data.normalized_text.slice(detail.data.model_input.length)}
                        </pre>
                      </details>
                    )}
                  </section>

                  <details className="triage-technical">
                    <summary>Technical details</summary>
                    <dl>
                      <div>
                        <dt>Decision source</dt>
                        <dd>
                          {detail.data.technical.decision_source === "rule"
                            ? `Rule · ${detail.data.technical.rule_id ?? "private"}`
                            : "AI model"}
                        </dd>
                      </div>
                      <div>
                        <dt>Model</dt>
                        <dd>{detail.data.technical.model_alias ?? "unavailable"}</dd>
                      </div>
                      <div>
                        <dt>Prompt</dt>
                        <dd>
                          {detail.data.technical.prompt_source ?? "unavailable"} /{" "}
                          {detail.data.technical.prompt_version ?? "unavailable"}
                        </dd>
                      </div>
                      <div>
                        <dt>Usage</dt>
                        <dd>
                          {detail.data.technical.total_tokens == null
                            ? "unavailable"
                            : `${detail.data.technical.prompt_tokens}/${
                                detail.data.technical.completion_tokens
                              }/${detail.data.technical.total_tokens}`}
                        </dd>
                      </div>
                      <div>
                        <dt>Timing</dt>
                        <dd>{timing(detail.data.technical.total_seconds)}</dd>
                      </div>
                      <div>
                        <dt>Trace</dt>
                        <dd>{detail.data.technical.trace_id ? "available" : "unavailable"}</dd>
                      </div>
                      <div>
                        <dt>Normalization</dt>
                        <dd>
                          {detail.data.content_source} · {detail.data.normalized_text.length}{" "}
                          characters
                        </dd>
                      </div>
                    </dl>
                  </details>
                </article>
              )}
            </section>
          </div>
        </>
      ) : (
        <TriageDiagnostics />
      )}
    </section>
  );
}

function TriageDiagnostics() {
  const [runFilter, setRunFilter] = useState<TriageRunFilter>("all");
  const [itemFilter, setItemFilter] =
    useState<DiagnosticItemFilter>("recommendations");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const runs = useQuery({
    queryKey: ["email-triage-runs", runFilter],
    queryFn: () => getTriageRuns(runFilter),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const backfills = useQuery({
    queryKey: ["email-triage-backfills"],
    queryFn: () => getTriageBackfills(5),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const selectedId = selectedRunId ?? runs.data?.items[0]?.run_id ?? null;
  const detail = useQuery({
    queryKey: ["email-triage-run", selectedId],
    queryFn: () => getTriageRun(selectedId ?? ""),
    enabled: selectedId !== null,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const visibleItems = useMemo(
    () =>
      (detail.data?.items ?? []).filter((item) => {
        if (itemFilter === "recommendations") return item.status === "succeeded";
        if (itemFilter === "reused") return item.status === "reused";
        return item.status === "failed" || item.status === "interrupted";
      }),
    [detail.data, itemFilter],
  );

  return (
    <section className="triage-diagnostics" aria-label="Email triage diagnostics">
      <header>
        <div>
          <p className="overline">ENGINEERING EVIDENCE</p>
          <h2>Diagnostics</h2>
        </div>
        <div className="triage-filters" aria-label="Run filters">
          {(["all", "completed", "issues", "interrupted"] as const).map((value) => (
            <button
              className={runFilter === value ? "is-selected" : undefined}
              key={value}
              onClick={() => {
                setRunFilter(value);
                setSelectedRunId(null);
              }}
              type="button"
            >
              {value}
            </button>
          ))}
        </div>
      </header>

      <section className="triage-backfills" aria-label="Historical backfill progress">
        <div className="triage-section-title">
          <h3>Historical backfill</h3>
          <span>operator-controlled · no schedule</span>
        </div>
        {backfills.data?.items.length === 0 && (
          <p className="triage-muted">No historical backfill has been created.</p>
        )}
        {backfills.data?.items.map((job) => (
          <article key={job.job_id}>
            <header>
              <strong>{job.status.replaceAll("_", " ")}</strong>
              <span>{job.segments_exhausted}/12 months scanned</span>
            </header>
            <p>
              {job.discovered_count} discovered · {job.succeeded_count} new ·{" "}
              {job.reused_count} reused · {job.pending_count} pending ·{" "}
              {job.failed_count + job.interrupted_count} issues
            </p>
            <small>
              Frozen range {formatDateTime(job.starts_at_utc)} to{" "}
              {formatDateTime(job.ends_at_utc)}
            </small>
          </article>
        ))}
      </section>

      <div className="triage-layout">
        <section className="triage-runs" aria-label="Recent diagnostic runs">
          <div className="triage-section-title">
            <h3>Recent runs</h3>
            <span>{runs.data?.count ?? 0} shown</span>
          </div>
          {runs.data?.items.map((run) => (
            <button
              className={selectedId === run.run_id ? "is-selected" : undefined}
              key={run.run_id}
              onClick={() => setSelectedRunId(run.run_id)}
              type="button"
            >
              <span>{run.status.replaceAll("_", " ")}</span>
              <strong>{formatDateTime(run.requested_at_utc)}</strong>
              <small>
                {run.document_count} messages · {run.succeeded_count} new ·{" "}
                {run.reused_count} reused · {run.failed_count + run.interrupted_count} issues
              </small>
            </button>
          ))}
        </section>

        <section className="triage-detail" aria-label="Diagnostic run detail">
          {!detail.data && <p className="triage-muted">Select a run.</p>}
          {detail.data && (
            <>
              <header className="triage-section-title">
                <div>
                  <p className="overline">RUN DETAIL</p>
                  <h3>{shortFingerprint(detail.data.run.run_id)}</h3>
                </div>
                <span>{detail.data.run.status.replaceAll("_", " ")}</span>
              </header>
              <dl className="triage-run-evidence">
                <div>
                  <dt>Query</dt>
                  <dd>{detail.data.run.query_text ?? "Legacy query unavailable"}</dd>
                </div>
                <div>
                  <dt>Documents</dt>
                  <dd>{detail.data.run.document_count}</dd>
                </div>
                <div>
                  <dt>Forced attempt</dt>
                  <dd>{detail.data.run.force_new_attempt ? "yes" : "no"}</dd>
                </div>
              </dl>
              <div className="triage-filters" aria-label="Diagnostic item filters">
                {(["recommendations", "reused", "failures"] as const).map((value) => (
                  <button
                    className={itemFilter === value ? "is-selected" : undefined}
                    key={value}
                    onClick={() => setItemFilter(value)}
                    type="button"
                  >
                    {value}
                  </button>
                ))}
              </div>
              <div className="triage-item-list">
                {visibleItems.map((item) => (
                  <article className="triage-item" key={item.ordinal}>
                    <header>
                      <strong>Item {item.ordinal}</strong>
                      <span>{item.status}</span>
                    </header>
                    <p>
                      {item.label ? `Recommendation: ${item.label}` : "No recommendation"}
                    </p>
                    {item.failure_category && (
                      <p className="triage-failure">Failure: {item.failure_category}</p>
                    )}
                    <details>
                      <summary>Evidence</summary>
                      <p>
                        Prompt {item.prompt_source ?? "unavailable"} /{" "}
                        {item.prompt_version ?? "unavailable"}
                      </p>
                      <p>Model {item.model_alias ?? "unavailable"}</p>
                      <p>Total time {timing(item.total_seconds)}</p>
                      <p>Trace {item.trace_id ? "available" : "unavailable"}</p>
                    </details>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </section>
  );
}
