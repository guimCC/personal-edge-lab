from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from personal_edge_lab.domain.ai import (
    CompletionResult,
    CompletionTiming,
    ModelIdentity,
    TokenUsage,
)
from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    TriageDecision,
    TriageEmail,
    TriageLabel,
    TriageProfile,
    TriageTraceRecord,
)
from personal_edge_lab.infrastructure.observability import langfuse as adapter
from personal_edge_lab.infrastructure.observability.langfuse import (
    LangfuseTriageRuntime,
    PromptPublicationError,
)
from personal_edge_lab.modules.email_triage.prompt import load_packaged_prompt


class Prompt:
    def __init__(
        self,
        *,
        fallback: bool = False,
        version: int = 7,
        config: dict[str, str] | None = None,
    ) -> None:
        self.is_fallback = fallback
        self.name = "personal-edge-lab/email-triage"
        self.version = version
        self.variables = ["taxonomy", "email_json"]
        self.config = config if config is not None else adapter._prompt_config()
        self.prompt = adapter._manifest_messages(load_packaged_prompt())

    def compile(self, **variables):
        return [
            {
                "role": item["role"],
                "content": item["content"]
                .replace("{{taxonomy}}", variables["taxonomy"])
                .replace("{{email_json}}", variables["email_json"]),
            }
            for item in self.prompt
        ]


class FakeLangfuse:
    instances = []
    prompt = Prompt()
    get_error = None
    created = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.observations = []
        self.flushed = False
        self.stopped = False
        type(self).instances.append(self)

    def get_prompt(self, *args, **kwargs):
        self.get_args = args
        self.get_kwargs = kwargs
        if type(self).get_error:
            raise type(self).get_error
        return type(self).prompt

    def create_prompt(self, **kwargs):
        type(self).created = kwargs
        return Prompt(version=8)

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.observations.append(kwargs)
        yield SimpleNamespace()

    def flush(self):
        self.flushed = True

    def shutdown(self):
        self.stopped = True


@contextmanager
def fake_propagate(**kwargs):
    FakeLangfuse.instances[-1].propagated = kwargs
    yield None


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    FakeLangfuse.instances = []
    FakeLangfuse.prompt = Prompt()
    FakeLangfuse.get_error = None
    FakeLangfuse.created = None
    monkeypatch.setattr(adapter, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(adapter, "propagate_attributes", fake_propagate)


def runtime() -> LangfuseTriageRuntime:
    return LangfuseTriageRuntime(
        public_key="p" * 64,
        secret_key="s" * 64,
        base_url="https://cloud.langfuse.com",
        timeout_seconds=2,
        release="0.11.0",
        manifest=load_packaged_prompt(),
    )


def variables() -> dict[str, str]:
    return {
        "taxonomy": '["work","billing","notification","newsletter","personal","other"]',
        "email_json": '{"message":"Invoice","sender":"billing@example.test","subject":"Bill"}',
    }


def test_remote_prompt_is_compiled_and_exact_version_is_retained() -> None:
    value = runtime().resolve(variables())
    assert value.identity.source is PromptSourceKind.LANGFUSE
    assert value.identity.version == "7"
    assert value.messages[-1].content == variables()["email_json"]
    observed = FakeLangfuse.instances[0].get_kwargs
    assert observed["cache_ttl_seconds"] == 300
    assert observed["max_retries"] == 0
    assert observed["fetch_timeout_seconds"] == 2


@pytest.mark.parametrize(
    "prompt",
    [
        Prompt(fallback=True),
        Prompt(config={}),
    ],
)
def test_missing_or_incompatible_remote_prompt_uses_packaged_fallback(prompt) -> None:
    FakeLangfuse.prompt = prompt
    value = runtime().resolve(variables())
    assert value.identity.source is PromptSourceKind.LOCAL_FALLBACK
    assert value.identity.version == "1.0.0"


def test_remote_failure_uses_packaged_fallback() -> None:
    FakeLangfuse.get_error = RuntimeError("sentinel provider body")
    value = runtime().resolve(variables())
    assert value.identity.source is PromptSourceKind.LOCAL_FALLBACK


@pytest.mark.parametrize(
    "compiled",
    [
        [{"role": "tool", "content": "invalid role"}],
        [{"role": "user", "content": "{{unresolved}}"}],
        [{"role": "user", "content": "x" * 4097}],
        [{"role": "user", "content": "ok", "unexpected": "field"}],
    ],
)
def test_malformed_or_excessive_remote_prompt_uses_fallback(compiled) -> None:
    prompt = Prompt()
    prompt.compile = lambda **_variables: compiled
    FakeLangfuse.prompt = prompt
    value = runtime().resolve(variables())
    assert value.identity.source is PromptSourceKind.LOCAL_FALLBACK


def test_identical_prompt_publication_is_idempotent() -> None:
    outcome, version = runtime().publish_packaged_prompt()
    assert (outcome, version) == ("unchanged", "7")
    assert FakeLangfuse.created is None


def test_changed_prompt_creates_and_promotes_one_version() -> None:
    FakeLangfuse.prompt.prompt[0]["content"] = "different"
    outcome, version = runtime().publish_packaged_prompt()
    assert (outcome, version) == ("published", "8")
    assert FakeLangfuse.created["labels"] == ["production"]
    assert FakeLangfuse.created["type"] == "chat"
    assert FakeLangfuse.created["commit_message"].endswith("release 0.11.0")


def test_publication_error_is_sanitized() -> None:
    FakeLangfuse.get_error = RuntimeError("secret provider body")
    with pytest.raises(PromptPublicationError) as captured:
        runtime().publish_packaged_prompt()
    assert str(captured.value) == "Langfuse prompt publication failed"
    assert "secret provider body" not in str(captured.value)


def test_trace_has_exact_root_and_generation_shape_with_prompt_link() -> None:
    runtime_value = runtime()
    prompt = runtime_value.resolve(variables())
    completion = CompletionResult(
        text='{"label":"billing","reason":"Invoice"}',
        identity=ModelIdentity(provider="llama_cpp", model_alias="qwen3-1.7b-q4-k-m"),
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        timing=CompletionTiming(queue_wait_seconds=0.2, provider_seconds=1.3),
    )
    trace_id = runtime_value.record(
        TriageTraceRecord(
            trace_id="1" * 32,
            operation_id="operation",
            email=TriageEmail("billing@example.test", "Bill", "Invoice"),
            prompt=prompt.identity,
            prompt_messages=prompt.messages,
            profile=TriageProfile(
                name="email-triage",
                version="1.0.0",
                taxonomy_version="1.0.0",
                schema_version="1.0.0",
                generation_parameters_version="1.0.0",
            ),
            provider="llama_cpp",
            model_alias="qwen3-1.7b-q4-k-m",
            completion=completion,
            raw_output=completion.text,
            decision=TriageDecision(TriageLabel.BILLING, "Invoice"),
            outcome="success",
        )
    )
    client = FakeLangfuse.instances[0]
    assert trace_id == "1" * 32
    assert [item["name"] for item in client.observations] == [
        "classify-email",
        "generate-triage-decision",
    ]
    assert client.observations[0]["as_type"] == "span"
    generation = client.observations[1]
    assert generation["as_type"] == "generation"
    assert generation["model"] == "qwen3-1.7b-q4-k-m"
    assert generation["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert generation["prompt"] is FakeLangfuse.prompt
    assert client.propagated["tags"] == ["email-triage", "synthetic"]


def test_close_flushes_and_shuts_down_short_lived_client() -> None:
    value = runtime()
    value.close()
    assert FakeLangfuse.instances[0].flushed is True
    assert FakeLangfuse.instances[0].stopped is True


def test_sdk_mask_removes_both_keys_recursively() -> None:
    runtime()
    mask = FakeLangfuse.instances[0].kwargs["mask"]
    masked = mask(
        data={
            "header": "Bearer " + ("s" * 64),
            "nested": ["public=" + ("p" * 64)],
        }
    )
    assert "s" * 64 not in repr(masked)
    assert "p" * 64 not in repr(masked)
    assert repr(masked).count("[REDACTED]") == 2
