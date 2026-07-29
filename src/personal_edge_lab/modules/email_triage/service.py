"""Bounded email-triage orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from personal_edge_lab.application.ports.ai import LanguageModel, LanguageModelError
from personal_edge_lab.application.ports.email_triage import (
    TriageDecisionDecoder,
    TriagePromptSource,
    TriageTraceSink,
)
from personal_edge_lab.domain.ai import (
    CompletionRequest,
    ReasoningMode,
    StructuredOutputContract,
)
from personal_edge_lab.domain.email_triage import (
    PreparedTriage,
    RedactedTriageTracePayload,
    SyntheticTriageTracePayload,
    TriageEmail,
    TriageEvidence,
    TriageOutputError,
    TriageProfile,
    TriageResult,
    TriageTraceRecord,
)

TRIAGE_LABEL_VALUES = (
    "mckinsey",
    "education",
    "job",
    "personal",
    "admin",
    "notification",
    "newsletter",
    "slop",
    "other",
)
TRIAGE_TAXONOMY = {
    "version": "2.0.0",
    "precedence": list(TRIAGE_LABEL_VALUES),
    "labels": {
        "mckinsey": (
            "McKinsey-specific work, recruiting, staffing, benefits, travel, events, "
            "or administration."
        ),
        "education": (
            "School, university, courses, learning programs, academic administration, "
            "or education communities."
        ),
        "job": (
            "All other current or former employment, professional recruiting, clients, "
            "colleagues, or work."
        ),
        "personal": (
            "Direct human correspondence primarily about a personal relationship or personal plans."
        ),
        "admin": (
            "Bills, banking, taxes, government, contracts, insurance, healthcare "
            "appointments, or account administration."
        ),
        "notification": (
            "Transactional messages triggered by an event or account activity, such as "
            "reservations, security alerts, or deliveries."
        ),
        "newsletter": (
            "A clearly identifiable recurring newsletter or publication sent for reading."
        ),
        "slop": (
            "Product changelogs, generic announcements, promotions, marketing, and "
            "repetitive bulk noise."
        ),
        "other": "Use only when no other category genuinely fits.",
    },
}
TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": list(TRIAGE_LABEL_VALUES)},
        "reason": {"type": "string", "minLength": 1, "maxLength": 160},
    },
    "required": ["label", "reason"],
    "additionalProperties": False,
}
DEFAULT_PROFILE = TriageProfile(
    name="email-triage",
    version="2.0.0",
    taxonomy_version="2.0.0",
    schema_version="2.0.0",
    generation_parameters_version="1.0.0",
)


class EmailTriageService:
    def __init__(
        self,
        *,
        model: LanguageModel,
        prompt_source: TriagePromptSource,
        decoder: TriageDecisionDecoder,
        trace_sink: TriageTraceSink,
        model_alias: str,
        profile: TriageProfile = DEFAULT_PROFILE,
    ) -> None:
        self._model = model
        self._prompt_source = prompt_source
        self._decoder = decoder
        self._trace_sink = trace_sink
        self._model_alias = model_alias
        self._profile = profile

    def classify(self, email: TriageEmail, *, operation_id: str) -> TriageResult:
        return self.classify_prepared(self.prepare(email), operation_id=operation_id)

    def prepare(self, email: TriageEmail) -> PreparedTriage:
        email_json = json.dumps(
            {"message": email.message, "sender": email.sender, "subject": email.subject},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        prompt = self._prompt_source.resolve(
            {
                "taxonomy": json.dumps(
                    TRIAGE_TAXONOMY,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "email_json": email_json,
            }
        )
        request = CompletionRequest(
            messages=prompt.messages,
            model_alias=self._model_alias,
            max_output_tokens=self._profile.max_output_tokens,
            temperature=self._profile.temperature,
            structured_output=StructuredOutputContract(
                name="email_triage_decision",
                schema=TRIAGE_SCHEMA,
            ),
            reasoning_mode=ReasoningMode.DISABLED,
        )
        return PreparedTriage(
            email=email,
            prompt=prompt,
            profile=self._profile,
            request=request,
        )

    def classify_prepared(
        self,
        prepared: PreparedTriage,
        *,
        operation_id: str,
        redacted_trace: RedactedTriageTracePayload | None = None,
    ) -> TriageResult:
        trace_id = _trace_id(operation_id)
        try:
            completion = self._model.complete(prepared.request)
        except LanguageModelError as error:
            self._safe_trace(
                TriageTraceRecord(
                    trace_id=trace_id,
                    operation_id=operation_id,
                    prompt=prepared.prompt.identity,
                    profile=prepared.profile,
                    provider="llama_cpp",
                    model_alias=self._model_alias,
                    usage=None,
                    timing=None,
                    payload=(
                        redacted_trace
                        if redacted_trace is not None
                        else SyntheticTriageTracePayload(
                            email=prepared.email,
                            prompt_messages=prepared.prompt.messages,
                            raw_output=None,
                            decision=None,
                        )
                    ),
                    outcome="failure",
                    failure_category=error.category.value,
                    failure_queue_wait_seconds=error.queue_wait_seconds,
                    failure_provider_seconds=error.provider_elapsed_seconds,
                    attempt_count=error.attempt_count,
                    retry_eligible=error.retry_eligible,
                    retry_after_seconds=error.retry_after_seconds,
                )
            )
            raise
        try:
            decision = self._decoder.decode(completion.text)
        except TriageOutputError:
            self._safe_trace(
                TriageTraceRecord(
                    trace_id=trace_id,
                    operation_id=operation_id,
                    prompt=prepared.prompt.identity,
                    profile=prepared.profile,
                    provider=completion.provider,
                    model_alias=completion.model_alias,
                    usage=completion.usage,
                    timing=completion.timing,
                    payload=(
                        redacted_trace
                        if redacted_trace is not None
                        else SyntheticTriageTracePayload(
                            email=prepared.email,
                            prompt_messages=prepared.prompt.messages,
                            raw_output=completion.text,
                            decision=None,
                        )
                    ),
                    outcome="failure",
                    failure_category="triage_output",
                )
            )
            raise
        recorded_trace_id = self._safe_trace(
            TriageTraceRecord(
                trace_id=trace_id,
                operation_id=operation_id,
                prompt=prepared.prompt.identity,
                profile=prepared.profile,
                provider=completion.provider,
                model_alias=completion.model_alias,
                usage=completion.usage,
                timing=completion.timing,
                payload=(
                    replace(
                        redacted_trace,
                        decision_sha256=_decision_hash(
                            decision.label.value,
                            _model_reason(decision),
                        ),
                        label=decision.label,
                        reason_chars=len(_model_reason(decision)),
                    )
                    if redacted_trace is not None
                    else SyntheticTriageTracePayload(
                        email=prepared.email,
                        prompt_messages=prepared.prompt.messages,
                        raw_output=completion.text,
                        decision=decision,
                    )
                ),
                outcome="success",
            )
        )
        return TriageResult(
            decision=decision,
            evidence=TriageEvidence(
                operation_id=operation_id,
                trace_id=recorded_trace_id,
                trace_unavailable=recorded_trace_id is None,
                prompt=prepared.prompt.identity,
                profile=prepared.profile,
                completion=completion,
            ),
        )

    def _safe_trace(self, record: TriageTraceRecord) -> str | None:
        try:
            return self._trace_sink.record(record)
        except Exception:
            return None


def _trace_id(operation_id: str) -> str:
    return hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:32]


def _model_reason(decision: object) -> str:
    reason = getattr(decision, "reason", None)
    if not isinstance(reason, str):
        raise TriageOutputError("model decision reason is unavailable")
    return reason


def _decision_hash(label: str, reason: str) -> str:
    value = json.dumps(
        {"label": label, "reason": reason},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
