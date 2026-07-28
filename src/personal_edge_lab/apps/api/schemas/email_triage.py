"""Protected email-triage review API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from personal_edge_lab.apps.api.schemas.common import ApiModel
from personal_edge_lab.domain.email_triage_review import TriageReviewContent, TriageRunFilter
from personal_edge_lab.domain.email_triage_runs import (
    TriageRunDetails,
    TriageRunItemSummary,
    TriageRunSummary,
)


class TriageRunSummaryResponse(ApiModel):
    run_id: str
    status: str
    query_sha256: str
    requested_limit: int
    force_new_attempt: bool
    requested_at_utc: datetime
    completed_at_utc: datetime | None
    document_count: int
    retrieval_failure_count: int
    succeeded_count: int
    reused_count: int
    failed_count: int
    interrupted_count: int

    @classmethod
    def from_domain(cls, value: TriageRunSummary) -> TriageRunSummaryResponse:
        return cls(
            run_id=value.run_id,
            status=value.status.value,
            query_sha256=value.query_sha256,
            requested_limit=value.requested_limit,
            force_new_attempt=value.force_new_attempt,
            requested_at_utc=value.requested_at,
            completed_at_utc=value.completed_at,
            document_count=value.document_count,
            retrieval_failure_count=value.retrieval_failure_count,
            succeeded_count=value.succeeded_count,
            reused_count=value.reused_count,
            failed_count=value.failed_count,
            interrupted_count=value.interrupted_count,
        )


class TriageRunListResponse(ApiModel):
    count: int
    limit: int
    status: TriageRunFilter
    items: list[TriageRunSummaryResponse]


class TriageRunItemResponse(ApiModel):
    ordinal: int
    message_fingerprint: str
    received_at_utc: datetime | None
    status: str
    label: str | None
    decision_sha256: str | None
    reason_chars: int | None
    failure_category: str | None
    prompt_source: str | None
    prompt_version: str | None
    profile_version: str | None
    model_alias: str | None
    trace_id: str | None
    queue_wait_seconds: float | None
    provider_seconds: float | None
    total_seconds: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    attempt_id: int | None
    review_available: bool

    @classmethod
    def from_domain(cls, value: TriageRunItemSummary) -> TriageRunItemResponse:
        return cls(
            ordinal=value.ordinal,
            message_fingerprint=value.message_fingerprint,
            received_at_utc=value.received_at,
            status=value.status.value,
            label=value.label.value if value.label is not None else None,
            decision_sha256=value.decision_sha256,
            reason_chars=value.reason_chars,
            failure_category=value.failure_category,
            prompt_source=value.prompt_source.value if value.prompt_source is not None else None,
            prompt_version=value.prompt_version,
            profile_version=value.profile_version,
            model_alias=value.model_alias,
            trace_id=value.trace_id,
            queue_wait_seconds=value.queue_wait_seconds,
            provider_seconds=value.provider_seconds,
            total_seconds=value.total_seconds,
            prompt_tokens=value.prompt_tokens,
            completion_tokens=value.completion_tokens,
            total_tokens=value.total_tokens,
            attempt_id=value.attempt_id,
            review_available=value.review_available,
        )


class TriageRunDetailResponse(ApiModel):
    run: TriageRunSummaryResponse
    items: list[TriageRunItemResponse]
    gmail_changes: Literal["none"] = "none"

    @classmethod
    def from_domain(cls, value: TriageRunDetails) -> TriageRunDetailResponse:
        return cls(
            run=TriageRunSummaryResponse.from_domain(value.run),
            items=[TriageRunItemResponse.from_domain(item) for item in value.items],
        )


class TriageReviewContentResponse(ApiModel):
    run_id: str
    ordinal: int
    message_fingerprint: str
    sender: str
    subject: str
    model_input: str
    normalized_remainder: str
    normalized_chars: int
    model_input_chars: int
    content_source: str
    cleanup_flags: list[str]
    source_truncated: bool
    model_input_truncated: bool
    metadata_truncated: bool
    identity_verified: bool
    api_call_count: Literal[1]
    elapsed_seconds: float
    gmail_changes: Literal["none"] = "none"

    @classmethod
    def from_domain(cls, value: TriageReviewContent) -> TriageReviewContentResponse:
        return cls(
            run_id=value.run_id,
            ordinal=value.ordinal,
            message_fingerprint=value.message_fingerprint,
            sender=value.sender,
            subject=value.subject,
            model_input=value.model_input,
            normalized_remainder=value.normalized_remainder,
            normalized_chars=value.normalized_chars,
            model_input_chars=value.model_input_chars,
            content_source=value.content_source.value,
            cleanup_flags=list(value.cleanup_flags),
            source_truncated=value.source_truncated,
            model_input_truncated=value.model_input_truncated,
            metadata_truncated=value.metadata_truncated,
            identity_verified=value.identity_verified,
            api_call_count=1,
            elapsed_seconds=value.elapsed_seconds,
        )
