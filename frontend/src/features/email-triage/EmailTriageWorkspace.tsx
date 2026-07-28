import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  ApiError,
  getTriageReviewContent,
  getTriageRun,
  getTriageRuns,
} from "../../api/client";
import type {
  TriageReviewContent,
  TriageRunFilter,
  TriageRunItem,
} from "../../api/contracts";
import { formatDateTime } from "../../shared/format";

type ItemFilter = "recommendations" | "reused" | "failures";

function shortFingerprint(value: string | null): string {
  return value ? value.slice(0, 16) : "unavailable";
}

function timing(value: number | null): string {
  return value == null ? "unavailable" : `${value.toFixed(3)}s`;
}

function itemMatches(item: TriageRunItem, filter: ItemFilter): boolean {
  if (filter === "recommendations") {
    return item.status === "succeeded";
  }
  if (filter === "reused") {
    return item.status === "reused";
  }
  return item.status === "failed" || item.status === "interrupted";
}

export function EmailTriageWorkspace() {
  const [runFilter, setRunFilter] = useState<TriageRunFilter>("all");
  const [itemFilter, setItemFilter] = useState<ItemFilter>("recommendations");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [privateContent, setPrivateContent] = useState<TriageReviewContent | null>(null);
  const [privateLoading, setPrivateLoading] = useState<number | null>(null);
  const [privateError, setPrivateError] = useState<string | null>(null);

  const runs = useQuery({
    queryKey: ["email-triage-runs", runFilter],
    queryFn: () => getTriageRuns(runFilter),
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
    () => (detail.data?.items ?? []).filter((item) => itemMatches(item, itemFilter)),
    [detail.data, itemFilter],
  );

  const loadContent = async (item: TriageRunItem) => {
    if (!selectedId) return;
    setPrivateContent(null);
    setPrivateError(null);
    setPrivateLoading(item.ordinal);
    try {
      setPrivateContent(await getTriageReviewContent(selectedId, item.ordinal));
    } catch (error) {
      setPrivateError(
        error instanceof ApiError
          ? "Private email content is unavailable for this item."
          : "The private-content response was invalid.",
      );
    } finally {
      setPrivateLoading(null);
    }
  };

  const closeContent = () => {
    setPrivateContent(null);
    setPrivateError(null);
  };

  return (
    <section className="triage-workspace" aria-labelledby="triage-workspace-title">
      <header className="triage-heading">
        <div>
          <p className="overline">SHADOW REVIEW</p>
          <h1 id="triage-workspace-title">Email triage</h1>
          <p>Review durable recommendations from manual runs. This workspace cannot run triage.</p>
        </div>
        <div className="triage-safety" role="status">
          <strong>Gmail labels applied: none</strong>
          <span>Read-only · content loads only when requested</span>
        </div>
      </header>

      <div className="triage-filters" aria-label="Run filters">
        {(["all", "completed", "issues", "interrupted"] as const).map((value) => (
          <button
            className={runFilter === value ? "is-selected" : undefined}
            key={value}
            onClick={() => {
              setRunFilter(value);
              setSelectedRunId(null);
              closeContent();
            }}
            type="button"
          >
            {value}
          </button>
        ))}
      </div>

      <div className="triage-layout">
        <section className="triage-runs" aria-labelledby="triage-runs-title">
          <div className="triage-section-title">
            <h2 id="triage-runs-title">Recent runs</h2>
            <span>{runs.data?.count ?? 0} shown</span>
          </div>
          {runs.isPending && <p className="triage-muted">Loading evidence…</p>}
          {runs.isError && <p role="alert">Run evidence is unavailable.</p>}
          {runs.data?.items.length === 0 && <p className="triage-muted">No matching runs.</p>}
          <div className="triage-run-list">
            {runs.data?.items.map((run) => (
              <button
                className={selectedId === run.run_id ? "is-selected" : undefined}
                key={run.run_id}
                onClick={() => {
                  setSelectedRunId(run.run_id);
                  closeContent();
                }}
                type="button"
              >
                <span className="triage-run-status">{run.status.replaceAll("_", " ")}</span>
                <strong>{formatDateTime(run.requested_at_utc)}</strong>
                <span>Query {shortFingerprint(run.query_sha256)}</span>
                <span>
                  {run.document_count} documents · {run.succeeded_count} new ·{" "}
                  {run.reused_count} reused · {run.failed_count + run.interrupted_count} issues
                </span>
                {run.force_new_attempt && <em>Forced attempt</em>}
              </button>
            ))}
          </div>
        </section>

        <section className="triage-detail" aria-labelledby="triage-detail-title">
          <div className="triage-section-title">
            <div>
              <p className="overline">RUN DETAIL</p>
              <h2 id="triage-detail-title">
                {selectedId ? shortFingerprint(selectedId) : "Select a run"}
              </h2>
            </div>
            {detail.data && <span>{detail.data.run.status.replaceAll("_", " ")}</span>}
          </div>
          {detail.isPending && selectedId && <p className="triage-muted">Loading items…</p>}
          {detail.isError && <p role="alert">Run detail is unavailable.</p>}
          {detail.data && (
            <>
              <dl className="triage-run-evidence">
                <div>
                  <dt>Requested</dt>
                  <dd>{detail.data.run.requested_limit}</dd>
                </div>
                <div>
                  <dt>Documents</dt>
                  <dd>{detail.data.run.document_count}</dd>
                </div>
                <div>
                  <dt>Retrieval failures</dt>
                  <dd>{detail.data.run.retrieval_failure_count}</dd>
                </div>
                <div>
                  <dt>Query fingerprint</dt>
                  <dd>{shortFingerprint(detail.data.run.query_sha256)}</dd>
                </div>
              </dl>

              <div className="triage-filters triage-item-filters" aria-label="Item filters">
                {(["recommendations", "reused", "failures"] as const).map((value) => (
                  <button
                    className={itemFilter === value ? "is-selected" : undefined}
                    key={value}
                    onClick={() => {
                      setItemFilter(value);
                      closeContent();
                    }}
                    type="button"
                  >
                    {value}
                  </button>
                ))}
              </div>

              <div className="triage-item-list">
                {visibleItems.length === 0 && (
                  <p className="triage-muted">No items match this view.</p>
                )}
                {visibleItems.map((item) => (
                  <article className="triage-item" key={item.ordinal}>
                    <header>
                      <div>
                        <span>ITEM {String(item.ordinal).padStart(2, "0")}</span>
                        <strong>{item.status}</strong>
                      </div>
                      {item.label && <mark>Recommendation · {item.label}</mark>}
                    </header>
                    <dl>
                      <div>
                        <dt>Message fingerprint</dt>
                        <dd>{shortFingerprint(item.message_fingerprint)}</dd>
                      </div>
                      <div>
                        <dt>Received</dt>
                        <dd>
                          {item.received_at_utc
                            ? formatDateTime(item.received_at_utc)
                            : "unavailable"}
                        </dd>
                      </div>
                      <div>
                        <dt>Prompt</dt>
                        <dd>
                          {item.prompt_source ?? "unavailable"} /{" "}
                          {item.prompt_version ?? "unavailable"}
                        </dd>
                      </div>
                      <div>
                        <dt>Profile / model</dt>
                        <dd>
                          {item.profile_version ?? "unavailable"} /{" "}
                          {item.model_alias ?? "unavailable"}
                        </dd>
                      </div>
                      <div>
                        <dt>Decision evidence</dt>
                        <dd>
                          {shortFingerprint(item.decision_sha256)} · reason{" "}
                          {item.reason_chars ?? "unavailable"} chars
                        </dd>
                      </div>
                      <div>
                        <dt>Trace</dt>
                        <dd>{item.trace_id ? "available" : "unavailable"}</dd>
                      </div>
                      <div>
                        <dt>Usage</dt>
                        <dd>
                          {item.total_tokens == null
                            ? "unavailable"
                            : `${item.prompt_tokens}/${item.completion_tokens}/${item.total_tokens}`}
                        </dd>
                      </div>
                      <div>
                        <dt>Timing</dt>
                        <dd>
                          queue {timing(item.queue_wait_seconds)} · provider{" "}
                          {timing(item.provider_seconds)} · total {timing(item.total_seconds)}
                        </dd>
                      </div>
                    </dl>
                    {item.failure_category && (
                      <p className="triage-failure">Failure: {item.failure_category}</p>
                    )}
                    {item.review_available && (
                      <button
                        className="triage-load-content"
                        disabled={privateLoading !== null}
                        onClick={() => loadContent(item)}
                        type="button"
                      >
                        {privateLoading === item.ordinal
                          ? "Loading private content…"
                          : "Load private email content"}
                      </button>
                    )}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>

      {(privateContent || privateError) && (
        <section className="triage-private" aria-label="Private email content">
          <header>
            <div>
              <p className="overline">PRIVATE · TRANSIENT</p>
              <h2>Email content</h2>
            </div>
            <button type="button" onClick={closeContent}>
              Close and clear
            </button>
          </header>
          {privateError && <p role="alert">{privateError}</p>}
          {privateContent && (
            <>
              <dl>
                <div>
                  <dt>Sender</dt>
                  <dd>{privateContent.sender}</dd>
                </div>
                <div>
                  <dt>Subject</dt>
                  <dd>{privateContent.subject || "(no subject)"}</dd>
                </div>
                <div>
                  <dt>Identity</dt>
                  <dd>Verified against stored hashes</dd>
                </div>
              </dl>
              <h3>Content seen by the model</h3>
              <pre>{privateContent.model_input}</pre>
              {privateContent.normalized_remainder && (
                <details>
                  <summary>
                    Normalized remainder ({privateContent.normalized_remainder.length} characters)
                  </summary>
                  <pre>{privateContent.normalized_remainder}</pre>
                </details>
              )}
              <p className="triage-private-note">
                Source: {privateContent.content_source} · normalized{" "}
                {privateContent.normalized_chars} characters · Gmail changes: none
              </p>
            </>
          )}
        </section>
      )}
    </section>
  );
}
