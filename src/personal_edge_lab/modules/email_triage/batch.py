"""Durable bounded orchestration for read-only mailbox triage."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from personal_edge_lab.application.ports.ai import LanguageModelError
from personal_edge_lab.application.ports.email import EmailSource, EmailSourceError
from personal_edge_lab.application.ports.email_triage_runs import TriageRunRepository
from personal_edge_lab.domain.email import EmailDocument, EmailRetrievalRequest
from personal_edge_lab.domain.email_triage import (
    MAX_MESSAGE_CHARS,
    PreparedTriage,
    RedactedTriageTracePayload,
    TriageEmail,
    TriageOutputError,
)
from personal_edge_lab.domain.email_triage_runs import (
    MailboxTriageItemResult,
    MailboxTriageResult,
    TriageEvaluationIdentity,
    TriageInputEvidence,
    TriageReservationStatus,
    TriageRunItemStatus,
    TriageRunStatus,
)
from personal_edge_lab.modules.email_triage.service import EmailTriageService

STALE_WORK_SECONDS = 300


class TriageMailboxBatch:
    def __init__(
        self,
        *,
        email_source: EmailSource,
        triage_service: EmailTriageService,
        repository: TriageRunRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.perf_counter,
        interrupted: Callable[[], bool] = lambda: False,
    ) -> None:
        self._email_source = email_source
        self._triage_service = triage_service
        self._repository = repository
        self._clock = clock
        self._monotonic = monotonic
        self._interrupted = interrupted

    def execute(
        self,
        request: EmailRetrievalRequest,
        *,
        run_id: str,
        operation_id: str,
        force_new_attempt: bool = False,
    ) -> MailboxTriageResult:
        if request.limit > 10:
            raise ValueError("mailbox triage limit must not exceed 10")
        started = self._monotonic()
        requested_at = self._clock()
        query_sha256 = _sha256(request.query)
        self._repository.recover_stale(
            stale_before=requested_at - timedelta(seconds=STALE_WORK_SECONDS),
            recovered_at=requested_at,
        )
        self._repository.create_run(
            run_id=run_id,
            operation_id=operation_id,
            query_sha256=query_sha256,
            requested_limit=request.limit,
            force_new_attempt=force_new_attempt,
            requested_at=requested_at,
        )
        self._repository.mark_retrieving(run_id, updated_at=self._clock())
        try:
            batch = self._email_source.retrieve(request)
        except EmailSourceError as error:
            self._repository.fail_before_items(
                run_id,
                category=error.category.value,
                completed_at=self._clock(),
            )
            raise
        self._repository.record_retrieval(
            run_id,
            document_count=len(batch.documents),
            failure_count=len(batch.failures),
            pages_fetched=batch.pages_fetched,
            api_call_count=batch.api_call_count,
            elapsed_seconds=batch.elapsed_seconds,
            has_more=batch.has_more,
            updated_at=self._clock(),
        )

        results: list[MailboxTriageItemResult] = []
        ordinal = 1
        for failure in batch.failures:
            recorded_at = self._clock()
            self._repository.record_source_failure(
                run_id,
                ordinal=ordinal,
                failure=failure,
                recorded_at=recorded_at,
            )
            results.append(
                MailboxTriageItemResult(
                    ordinal=ordinal,
                    message_fingerprint=_sha256(
                        failure.message_id.value
                        if failure.message_id is not None
                        else f"{run_id}:source-failure:{ordinal}"
                    ),
                    received_at=None,
                    status=TriageRunItemStatus.FAILED,
                    failure_category=failure.category.value,
                )
            )
            ordinal += 1

        for document_index, document in enumerate(batch.documents):
            if self._interrupted():
                ordinal = self._record_interrupted_documents(
                    run_id,
                    ordinal=ordinal,
                    documents=batch.documents[document_index:],
                    results=results,
                )
                del ordinal
                completed_at = self._clock()
                self._repository.complete_run(
                    run_id,
                    status=TriageRunStatus.INTERRUPTED,
                    completed_at=completed_at,
                )
                return self._result(
                    run_id,
                    query_sha256,
                    request.limit,
                    results,
                    len(batch.failures),
                    TriageRunStatus.INTERRUPTED,
                    started,
                )
            result = self._classify_document(
                document,
                run_id=run_id,
                ordinal=ordinal,
                force_new_attempt=force_new_attempt,
            )
            results.append(result)
            ordinal += 1

        has_failures = bool(batch.failures) or any(
            item.status is TriageRunItemStatus.FAILED for item in results
        )
        status = (
            TriageRunStatus.COMPLETED_WITH_FAILURES
            if has_failures
            else TriageRunStatus.COMPLETED_WITH_RESULTS
        )
        self._repository.complete_run(run_id, status=status, completed_at=self._clock())
        return self._result(
            run_id,
            query_sha256,
            request.limit,
            results,
            len(batch.failures),
            status,
            started,
        )

    def _classify_document(
        self,
        document: EmailDocument,
        *,
        run_id: str,
        ordinal: int,
        force_new_attempt: bool,
    ) -> MailboxTriageItemResult:
        evidence, email = _input_evidence(document)
        try:
            prepared = self._triage_service.prepare(email)
        except Exception:
            recorded_at = self._clock()
            self._repository.record_item_failure(
                run_id,
                ordinal=ordinal,
                message_id=document.message_id.value,
                message_fingerprint=evidence.message_fingerprint,
                received_at=document.received_at,
                category="triage_input",
                recorded_at=recorded_at,
            )
            return _failed_item(ordinal, evidence, "triage_input")

        identity = _evaluation_identity(evidence, prepared)
        item_operation_id = _sha256(f"{run_id}:{ordinal}:{identity.identity_sha256}")[:32]
        reservation = self._repository.reserve(
            run_id,
            ordinal=ordinal,
            identity=identity,
            operation_id=item_operation_id,
            force_new_attempt=force_new_attempt,
            reserved_at=self._clock(),
        )
        if reservation.status is TriageReservationStatus.REUSED:
            assert reservation.decision is not None
            return MailboxTriageItemResult(
                ordinal=ordinal,
                message_fingerprint=evidence.message_fingerprint,
                received_at=evidence.received_at,
                status=TriageRunItemStatus.REUSED,
                sender=document.sender,
                subject=document.subject,
                label=reservation.decision.label,
                trace_id=reservation.trace_id,
                prompt=prepared.prompt.identity,
                model_alias=prepared.request.model_alias,
            )
        if reservation.status is TriageReservationStatus.CONCURRENT:
            return _failed_item(ordinal, evidence, "concurrent_evaluation")
        assert reservation.attempt_id is not None
        self._repository.mark_attempt_running(
            attempt_id=reservation.attempt_id,
            run_id=run_id,
            ordinal=ordinal,
            started_at=self._clock(),
        )
        redacted_trace = RedactedTriageTracePayload(
            content_sha256=evidence.model_input_sha256,
            decision_sha256=None,
            sender_chars=evidence.sender_chars,
            subject_chars=evidence.subject_chars,
            message_chars=evidence.model_message_chars,
            source=evidence.content_source.value,
            cleanup_flags=evidence.cleanup_flags,
        )
        try:
            triage = self._triage_service.classify_prepared(
                prepared,
                operation_id=item_operation_id,
                redacted_trace=redacted_trace,
            )
        except LanguageModelError as error:
            self._repository.fail_attempt(
                attempt_id=reservation.attempt_id,
                run_id=run_id,
                ordinal=ordinal,
                category=error.category.value,
                provider="llama_cpp",
                model_alias=prepared.request.model_alias,
                queue_wait_seconds=error.queue_wait_seconds,
                provider_seconds=error.provider_elapsed_seconds,
                attempt_count=error.attempt_count,
                retry_eligible=error.retry_eligible,
                retry_after_seconds=error.retry_after_seconds,
                trace_id=None,
                trace_unavailable=True,
                completed_at=self._clock(),
            )
            return MailboxTriageItemResult(
                ordinal=ordinal,
                message_fingerprint=evidence.message_fingerprint,
                received_at=evidence.received_at,
                status=TriageRunItemStatus.FAILED,
                failure_category=error.category.value,
                provider="llama_cpp",
                model_alias=prepared.request.model_alias,
                queue_wait_seconds=error.queue_wait_seconds,
                provider_seconds=error.provider_elapsed_seconds,
                total_seconds=(
                    error.queue_wait_seconds + error.provider_elapsed_seconds
                    if error.provider_elapsed_seconds is not None
                    else error.queue_wait_seconds
                ),
            )
        except TriageOutputError:
            self._repository.fail_attempt(
                attempt_id=reservation.attempt_id,
                run_id=run_id,
                ordinal=ordinal,
                category="triage_output",
                provider="llama_cpp",
                model_alias=prepared.request.model_alias,
                queue_wait_seconds=0,
                provider_seconds=None,
                attempt_count=1,
                retry_eligible=False,
                retry_after_seconds=None,
                trace_id=None,
                trace_unavailable=True,
                completed_at=self._clock(),
            )
            return _failed_item(ordinal, evidence, "triage_output")
        except Exception:
            self._repository.fail_attempt(
                attempt_id=reservation.attempt_id,
                run_id=run_id,
                ordinal=ordinal,
                category="unexpected_failure",
                provider=None,
                model_alias=prepared.request.model_alias,
                queue_wait_seconds=0,
                provider_seconds=None,
                attempt_count=1,
                retry_eligible=False,
                retry_after_seconds=None,
                trace_id=None,
                trace_unavailable=True,
                completed_at=self._clock(),
            )
            return _failed_item(ordinal, evidence, "unexpected_failure")

        self._repository.complete_attempt(
            attempt_id=reservation.attempt_id,
            run_id=run_id,
            ordinal=ordinal,
            decision=triage.decision,
            completion=triage.evidence.completion,
            trace_id=triage.evidence.trace_id,
            trace_unavailable=triage.evidence.trace_unavailable,
            completed_at=self._clock(),
        )
        usage = triage.evidence.completion.usage
        return MailboxTriageItemResult(
            ordinal=ordinal,
            message_fingerprint=evidence.message_fingerprint,
            received_at=evidence.received_at,
            status=TriageRunItemStatus.SUCCEEDED,
            sender=document.sender,
            subject=document.subject,
            label=triage.decision.label,
            reason=triage.decision.reason,
            trace_id=triage.evidence.trace_id,
            prompt=triage.evidence.prompt,
            provider=triage.evidence.completion.provider,
            model_alias=triage.evidence.completion.model_alias,
            queue_wait_seconds=triage.evidence.completion.timing.queue_wait_seconds,
            provider_seconds=triage.evidence.completion.timing.provider_seconds,
            total_seconds=triage.evidence.completion.elapsed_seconds,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )

    def _record_interrupted_documents(
        self,
        run_id: str,
        *,
        ordinal: int,
        documents: tuple[EmailDocument, ...],
        results: list[MailboxTriageItemResult],
    ) -> int:
        for document in documents:
            evidence, _email = _input_evidence(document)
            recorded_at = self._clock()
            self._repository.record_item_failure(
                run_id,
                ordinal=ordinal,
                message_id=document.message_id.value,
                message_fingerprint=evidence.message_fingerprint,
                received_at=document.received_at,
                category="interrupted",
                recorded_at=recorded_at,
                interrupted=True,
            )
            results.append(
                MailboxTriageItemResult(
                    ordinal=ordinal,
                    message_fingerprint=evidence.message_fingerprint,
                    received_at=evidence.received_at,
                    status=TriageRunItemStatus.INTERRUPTED,
                    failure_category="interrupted",
                )
            )
            ordinal += 1
        return ordinal

    def _result(
        self,
        run_id: str,
        query_sha256: str,
        requested_limit: int,
        items: list[MailboxTriageItemResult],
        retrieval_failure_count: int,
        status: TriageRunStatus,
        started: float,
    ) -> MailboxTriageResult:
        return MailboxTriageResult(
            run_id=run_id,
            status=status,
            query_sha256=query_sha256,
            requested_limit=requested_limit,
            items=tuple(items),
            retrieval_failure_count=retrieval_failure_count,
            elapsed_seconds=self._monotonic() - started,
        )


def _input_evidence(document: EmailDocument) -> tuple[TriageInputEvidence, TriageEmail]:
    model_message = document.text[:MAX_MESSAGE_CHARS]
    email = TriageEmail(
        sender=document.sender,
        subject=document.subject,
        message=model_message,
    )
    canonical_input = json.dumps(
        {"message": email.message, "sender": email.sender, "subject": email.subject},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    cleanup_flags = tuple(
        name
        for name, enabled in (
            ("quoted_text_removed", document.quoted_text_removed),
            ("signature_removed", document.signature_removed),
            ("tracking_removed", document.tracking_removed),
            ("duplicate_lines_removed", document.duplicate_lines_removed),
        )
        if enabled
    )
    return (
        TriageInputEvidence(
            message_id=document.message_id,
            thread_id=document.thread_id,
            received_at=document.received_at,
            message_fingerprint=_sha256(document.message_id.value),
            normalized_sha256=_sha256(document.text),
            model_input_sha256=_sha256(canonical_input),
            sender_chars=len(document.sender),
            subject_chars=len(document.subject),
            normalized_chars=len(document.text),
            model_message_chars=len(model_message),
            original_size_bytes=document.original_size_bytes,
            content_source=document.content_source,
            source_truncated=document.truncated,
            model_input_truncated=len(document.text) > len(model_message),
            metadata_truncated=document.metadata_truncated,
            cleanup_flags=cleanup_flags,
        ),
        email,
    )


def _evaluation_identity(
    evidence: TriageInputEvidence,
    prepared: PreparedTriage,
) -> TriageEvaluationIdentity:
    values = {
        "gmail_message_id": evidence.message_id.value,
        "model_input_sha256": evidence.model_input_sha256,
        "profile_name": prepared.profile.name,
        "profile_version": prepared.profile.version,
        "taxonomy_version": prepared.profile.taxonomy_version,
        "schema_version": prepared.profile.schema_version,
        "generation_parameters_version": prepared.profile.generation_parameters_version,
        "prompt_name": prepared.prompt.identity.name,
        "prompt_source": prepared.prompt.identity.source.value,
        "prompt_version": prepared.prompt.identity.version,
        "model_alias": prepared.request.model_alias,
    }
    canonical = json.dumps(values, separators=(",", ":"), sort_keys=True)
    return TriageEvaluationIdentity(
        identity_sha256=_sha256(canonical),
        input=evidence,
        profile_name=prepared.profile.name,
        profile_version=prepared.profile.version,
        taxonomy_version=prepared.profile.taxonomy_version,
        schema_version=prepared.profile.schema_version,
        generation_parameters_version=prepared.profile.generation_parameters_version,
        prompt=prepared.prompt.identity,
        model_alias=prepared.request.model_alias,
    )


def _failed_item(
    ordinal: int,
    evidence: TriageInputEvidence,
    category: str,
) -> MailboxTriageItemResult:
    return MailboxTriageItemResult(
        ordinal=ordinal,
        message_fingerprint=evidence.message_fingerprint,
        received_at=evidence.received_at,
        status=TriageRunItemStatus.FAILED,
        failure_category=category,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
