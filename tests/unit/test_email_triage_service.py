from __future__ import annotations

import json

import pytest

from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModelError,
)
from personal_edge_lab.application.ports.email_triage import NoOpTriageTraceSink
from personal_edge_lab.domain.ai import (
    CompletionResult,
    CompletionTiming,
    ModelIdentity,
    ReasoningMode,
)
from personal_edge_lab.domain.email_triage import TriageEmail, TriageOutputError
from personal_edge_lab.infrastructure.ai.triage_decoder import (
    PydanticTriageDecisionDecoder,
)
from personal_edge_lab.modules.email_triage.prompt import LocalTriagePromptSource
from personal_edge_lab.modules.email_triage.service import EmailTriageService


class Model:
    def __init__(self, text: str) -> None:
        self.text = text
        self.request = None

    def complete(self, request):
        self.request = request
        return CompletionResult(
            text=self.text,
            identity=ModelIdentity(
                provider="llama_cpp",
                model_alias=request.model_alias,
            ),
            usage=None,
            timing=CompletionTiming(queue_wait_seconds=0.25, provider_seconds=1.5),
        )


class Sink:
    def __init__(self) -> None:
        self.records = []

    def record(self, record):
        self.records.append(record)
        return record.trace_id

    def close(self):
        return None


def service(model, sink=None):
    return EmailTriageService(
        model=model,
        prompt_source=LocalTriagePromptSource(),
        decoder=PydanticTriageDecisionDecoder(),
        trace_sink=sink or NoOpTriageTraceSink(),
        model_alias="qwen3-1.7b-q4-k-m",
    )


def test_service_builds_structured_request_and_versioned_evidence() -> None:
    model = Model('{"label":"billing","reason":"The message contains an invoice"}')
    sink = Sink()
    result = service(model, sink).classify(
        TriageEmail("billing@example.test", "Invoice", "Amount due"),
        operation_id="stable-operation",
    )
    assert model.request.max_output_tokens == 64
    assert model.request.reasoning_mode is ReasoningMode.DISABLED
    assert model.request.structured_output.name == "email_triage_decision"
    assert model.request.structured_output.schema["additionalProperties"] is False
    email_payload = json.loads(model.request.messages[-1].content)
    assert email_payload["sender"] == "billing@example.test"
    assert result.evidence.profile.taxonomy_version == "1.0.0"
    assert result.evidence.trace_id == sink.records[0].trace_id
    assert len(result.evidence.trace_id) == 32


def test_trace_id_is_deterministic_for_operation() -> None:
    email = TriageEmail("billing@example.test", "Invoice", "Amount due")
    first = Sink()
    second = Sink()
    service(Model('{"label":"billing","reason":"Invoice"}'), first).classify(
        email, operation_id="same"
    )
    service(Model('{"label":"billing","reason":"Invoice"}'), second).classify(
        email, operation_id="same"
    )
    assert first.records[0].trace_id == second.records[0].trace_id


def test_empty_transport_completion_is_typed_triage_failure() -> None:
    sink = Sink()
    with pytest.raises(TriageOutputError):
        service(Model(""), sink).classify(
            TriageEmail("sender@example.test", "Subject", ""),
            operation_id="empty",
        )
    assert sink.records[0].failure_category == "triage_output"


@pytest.mark.parametrize("category", list(CompletionFailureCategory))
def test_inference_failure_is_recorded_and_re_raised(
    category: CompletionFailureCategory,
) -> None:
    class FailureModel:
        def complete(self, request):
            del request
            raise LanguageModelError(
                "sanitized",
                category=category,
                retry_eligible=True,
                queue_wait_seconds=0.5,
                provider_elapsed_seconds=1.25,
                attempt_count=1,
                retry_after_seconds=2,
            )

    sink = Sink()
    with pytest.raises(LanguageModelError):
        service(FailureModel(), sink).classify(
            TriageEmail("sender@example.test", "Subject", ""),
            operation_id="timeout",
        )
    assert sink.records[0].failure_category == category.value
    assert sink.records[0].failure_queue_wait_seconds == 0.5
    assert sink.records[0].failure_provider_seconds == 1.25
    assert sink.records[0].retry_after_seconds == 2


def test_trace_failure_never_invalidates_inference() -> None:
    class BrokenSink:
        def record(self, record):
            del record
            raise RuntimeError("unavailable")

        def close(self):
            return None

    result = service(
        Model('{"label":"other","reason":"No specific category"}'),
        BrokenSink(),
    ).classify(
        TriageEmail("sender@example.test", "Subject", ""),
        operation_id="trace-down",
    )
    assert result.evidence.trace_unavailable is True
    assert result.evidence.trace_id is None
