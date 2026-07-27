"""Bounded email-triage orchestration."""

from __future__ import annotations

import hashlib
import json

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
    TriageEmail,
    TriageEvidence,
    TriageOutputError,
    TriageProfile,
    TriageResult,
    TriageTraceRecord,
)

TRIAGE_LABEL_VALUES = (
    "work",
    "billing",
    "notification",
    "newsletter",
    "personal",
    "other",
)
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
    version="1.0.0",
    taxonomy_version="1.0.0",
    schema_version="1.0.0",
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
        email_json = json.dumps(
            {"message": email.message, "sender": email.sender, "subject": email.subject},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        prompt = self._prompt_source.resolve(
            {
                "taxonomy": json.dumps(TRIAGE_LABEL_VALUES, separators=(",", ":")),
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
        trace_id = _trace_id(operation_id)
        try:
            completion = self._model.complete(request)
        except LanguageModelError as error:
            self._safe_trace(
                TriageTraceRecord(
                    trace_id=trace_id,
                    operation_id=operation_id,
                    email=email,
                    prompt=prompt.identity,
                    prompt_messages=prompt.messages,
                    profile=self._profile,
                    provider="llama_cpp",
                    model_alias=self._model_alias,
                    completion=None,
                    raw_output=None,
                    decision=None,
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
                    email=email,
                    prompt=prompt.identity,
                    prompt_messages=prompt.messages,
                    profile=self._profile,
                    provider=completion.provider,
                    model_alias=completion.model_alias,
                    completion=completion,
                    raw_output=completion.text,
                    decision=None,
                    outcome="failure",
                    failure_category="triage_output",
                )
            )
            raise
        recorded_trace_id = self._safe_trace(
            TriageTraceRecord(
                trace_id=trace_id,
                operation_id=operation_id,
                email=email,
                prompt=prompt.identity,
                prompt_messages=prompt.messages,
                profile=self._profile,
                provider=completion.provider,
                model_alias=completion.model_alias,
                completion=completion,
                raw_output=completion.text,
                decision=decision,
                outcome="success",
            )
        )
        return TriageResult(
            decision=decision,
            evidence=TriageEvidence(
                operation_id=operation_id,
                trace_id=recorded_trace_id,
                trace_unavailable=recorded_trace_id is None,
                prompt=prompt.identity,
                profile=self._profile,
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
