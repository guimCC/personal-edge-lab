"""Protected email-triage review API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from personal_edge_lab.apps.api.schemas.common import ApiModel
from personal_edge_lab.domain.email_triage_messages import (
    TriageMessageDetail,
    TriageMessageFilter,
    TriageMessageSummary,
)
from personal_edge_lab.domain.email_triage_review import TriageRunFilter
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
    query_text: str | None

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
            query_text=value.query_text,
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
    decision_source: str | None
    rule_id: str | None
    rule_version: str | None

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
            decision_source=(
                value.decision_source.value if value.decision_source is not None else None
            ),
            rule_id=value.rule_id,
            rule_version=value.rule_version,
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


class TriageMessageSummaryResponse(ApiModel):
    record_id: str
    received_at_utc: datetime
    sender: str
    subject: str
    label: str | None
    reason_preview: str | None
    latest_status: str
    latest_failure_category: str | None
    last_triaged_at_utc: datetime
    model_input_truncated: bool
    source_truncated: bool
    has_recommendation: bool
    decision_source: str | None
    rule_id: str | None
    rule_version: str | None

    @classmethod
    def from_domain(cls, value: TriageMessageSummary) -> TriageMessageSummaryResponse:
        return cls(
            record_id=value.record_id,
            received_at_utc=value.received_at,
            sender=value.sender,
            subject=value.subject,
            label=value.label.value if value.label is not None else None,
            reason_preview=value.reason,
            latest_status=value.latest_status.value,
            latest_failure_category=value.latest_failure_category,
            last_triaged_at_utc=value.last_triaged_at,
            model_input_truncated=value.model_input_truncated,
            source_truncated=value.source_truncated,
            has_recommendation=value.has_recommendation,
            decision_source=(
                value.decision_source.value if value.decision_source is not None else None
            ),
            rule_id=value.rule_id,
            rule_version=value.rule_version,
        )


class TriageMessageListResponse(ApiModel):
    count: int
    limit: int
    status: TriageMessageFilter
    label: str | None
    next_cursor: str | None
    items: list[TriageMessageSummaryResponse]


class TriageMessageTechnicalResponse(ApiModel):
    run_id: str
    item_ordinal: int
    attempt_id: int | None
    decision_sha256: str | None
    prompt_source: str | None
    prompt_version: str | None
    profile_version: str | None
    taxonomy_version: str | None
    schema_version: str | None
    generation_parameters_version: str | None
    provider: str | None
    model_alias: str | None
    trace_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    queue_wait_seconds: float | None
    provider_seconds: float | None
    total_seconds: float | None
    decision_source: str | None
    rule_id: str | None
    rule_version: str | None


class TriageMessageDetailResponse(ApiModel):
    summary: TriageMessageSummaryResponse
    normalized_text: str
    model_input: str
    normalized_sha256: str
    model_input_sha256: str
    original_size_bytes: int
    content_source: str
    cleanup_flags: list[str]
    metadata_truncated: bool
    technical: TriageMessageTechnicalResponse
    gmail_changes: Literal["none"] = "none"

    @classmethod
    def from_domain(cls, value: TriageMessageDetail) -> TriageMessageDetailResponse:
        technical = value.technical
        return cls(
            summary=TriageMessageSummaryResponse.from_domain(value.summary),
            normalized_text=value.normalized_text,
            model_input=value.model_input,
            normalized_sha256=value.normalized_sha256,
            model_input_sha256=value.model_input_sha256,
            original_size_bytes=value.original_size_bytes,
            content_source=value.content_source.value,
            cleanup_flags=list(value.cleanup_flags),
            metadata_truncated=value.metadata_truncated,
            technical=TriageMessageTechnicalResponse(
                run_id=technical.run_id,
                item_ordinal=technical.item_ordinal,
                attempt_id=technical.attempt_id,
                decision_sha256=technical.decision_sha256,
                prompt_source=(
                    technical.prompt_source.value if technical.prompt_source is not None else None
                ),
                prompt_version=technical.prompt_version,
                profile_version=technical.profile_version,
                taxonomy_version=technical.taxonomy_version,
                schema_version=technical.schema_version,
                generation_parameters_version=technical.generation_parameters_version,
                provider=technical.provider,
                model_alias=technical.model_alias,
                trace_id=technical.trace_id,
                prompt_tokens=technical.prompt_tokens,
                completion_tokens=technical.completion_tokens,
                total_tokens=technical.total_tokens,
                queue_wait_seconds=technical.queue_wait_seconds,
                provider_seconds=technical.provider_seconds,
                total_seconds=technical.total_seconds,
                decision_source=(
                    technical.decision_source.value
                    if technical.decision_source is not None
                    else None
                ),
                rule_id=technical.rule_id,
                rule_version=technical.rule_version,
            ),
        )
