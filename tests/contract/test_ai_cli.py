from __future__ import annotations

import io
import logging

import httpx

from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModelError,
)
from personal_edge_lab.apps.ai_cli import __main__ as ai_cli
from personal_edge_lab.apps.ai_cli.__main__ import main

API_KEY = "a" * 64
OPERATION_ID = "operation-123"
PROMPT = "private diagnostic prompt"
SERVER_MODEL_PATH = "/home/arduino/models/Qwen3-1.7B-Q4_K_M.gguf"


def run_cli(arguments: list[str], handler):
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        arguments,
        stdout=stdout,
        stderr=stderr,
        transport=httpx.MockTransport(handler),
        operation_id_factory=lambda: OPERATION_ID,
    )
    return exit_code, stdout.getvalue(), stderr.getvalue()


def configure_completion(monkeypatch, tmp_path) -> None:
    key = tmp_path / "unoq.key"
    key.write_text(f"{API_KEY}\n", encoding="utf-8")
    key.chmod(0o600)
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", str(key))
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://uno.local:8080")


def success_payload(content: str = "ready") -> dict[str, object]:
    return {
        "model": SERVER_MODEL_PATH,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
    }


def test_synthetic_triage_uses_local_fallback_and_strict_structured_request(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    configure_completion(monkeypatch, tmp_path)
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    observed_payload = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_payload
        observed_payload = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json=success_payload('{"label":"admin","reason":"The message contains an invoice"}'),
        )

    caplog.set_level(logging.INFO)
    exit_code, stdout, stderr = run_cli(
        ["triage", "--fixture", "synthetic-invoice"],
        handler,
    )
    assert exit_code == 0
    assert stderr == ""
    assert "Label: admin" in stdout
    assert "Reason: The message contains an invoice" in stdout
    assert "Prompt source: local_fallback" in stdout
    assert "Prompt version: 2.0.0" in stdout
    assert "Trace: unavailable" in stdout
    assert observed_payload["max_tokens"] == 64
    assert observed_payload["reasoning_effort"] == "none"
    assert observed_payload["response_format"]["type"] == "json_schema"
    assert "billing@example.test" not in caplog.text
    assert "The message contains an invoice" not in caplog.text
    assert API_KEY not in caplog.text


def test_triage_rejects_invalid_model_output(monkeypatch, tmp_path, caplog) -> None:
    configure_completion(monkeypatch, tmp_path)
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    caplog.set_level(logging.WARNING)
    exit_code, stdout, stderr = run_cli(
        ["triage", "--fixture", "synthetic-invoice"],
        lambda _: httpx.Response(200, json=success_payload("not json")),
    )
    assert exit_code == 5
    assert stdout == ""
    assert "invalid_model_output" in stderr
    assert "not json" not in caplog.text


def test_synthetic_taxonomy_evaluation_reports_differences_without_quality_gate(
    monkeypatch,
    tmp_path,
) -> None:
    configure_completion(monkeypatch, tmp_path)
    labels = iter(
        [
            "mckinsey",
            "education",
            "job",
            "personal",
            "admin",
            "notification",
            "newsletter",
            "other",
            "other",
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        label = next(labels)
        return httpx.Response(
            200,
            json=success_payload(f'{{"label":"{label}","reason":"Synthetic evaluation reason"}}'),
        )

    exit_code, stdout, stderr = run_cli(
        ["evaluate", "--fixture-set", "taxonomy-v2-core"],
        handler,
    )

    assert exit_code == 0
    assert stderr == ""
    assert "Baseline: 8/9" in stdout
    assert "slop-changelog: expected=slop actual=other different" in stdout
    assert "Quality threshold: none" in stdout
    assert "Traces: none" in stdout


def test_health_works_while_disabled_and_without_key(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", "/missing/key")
    exit_code, stdout, stderr = run_cli(
        ["health"],
        lambda _: httpx.Response(200, json={"status": "ok"}),
    )
    assert exit_code == 0
    assert "Health: live" in stdout
    assert "Provider: llama_cpp" in stdout
    assert OPERATION_ID in stdout
    assert stderr == ""


def test_health_treats_documented_loading_response_as_live(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    exit_code, stdout, stderr = run_cli(
        ["health"],
        lambda _: httpx.Response(503, json={"error": {"message": "Loading model"}}),
    )
    assert exit_code == 0
    assert "Health: live" in stdout
    assert stderr == ""


def test_ready_works_while_disabled_and_without_key(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", "/missing/key")
    exit_code, stdout, stderr = run_cli(
        ["ready"],
        lambda _: httpx.Response(200, json={"status": "ok"}),
    )
    assert exit_code == 0
    assert "Readiness: ready" in stdout
    assert "Provider: llama_cpp" in stdout
    assert stderr == ""


def test_ready_reports_loading_as_not_ready(monkeypatch, caplog) -> None:
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    caplog.set_level(logging.WARNING)
    exit_code, stdout, stderr = run_cli(
        ["ready"],
        lambda _: httpx.Response(503, json={"error": {"message": "Loading model"}}),
    )
    assert exit_code == 5
    assert stdout == ""
    assert "not_ready" in stderr
    assert "attempt_count=1" in caplog.text


def test_complete_is_blocked_before_network_when_disabled(monkeypatch) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    exit_code, stdout, stderr = run_cli(["complete", "--text", "hello"], handler)
    assert exit_code == 2
    assert calls == 0
    assert stdout == ""
    assert "Configuration error" in stderr


def test_success_prints_sanitized_human_output_without_provider_path(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    configure_completion(monkeypatch, tmp_path)
    caplog.set_level(logging.INFO)
    exit_code, stdout, stderr = run_cli(
        ["complete", "--text", PROMPT],
        lambda _: httpx.Response(200, json=success_payload("ready\x1b[31m\nnext")),
    )
    assert exit_code == 0
    assert "Completion:\nready�[31m\nnext" in stdout
    assert "Model: qwen3-1.7b-q4-k-m" in stdout
    assert "Tokens: prompt=5 completion=1 total=6" in stdout
    assert "Queue wait:" in stdout
    assert "Provider elapsed:" in stdout
    assert OPERATION_ID in stdout
    assert SERVER_MODEL_PATH not in stdout
    assert stderr == ""
    assert PROMPT not in caplog.text
    assert API_KEY not in caplog.text
    assert SERVER_MODEL_PATH not in caplog.text
    assert "outcome=success" in caplog.text
    assert "queue_wait_seconds=" in caplog.text
    assert "provider_seconds=" in caplog.text
    assert "attempt_count=1" in caplog.text


def test_oversized_input_is_rejected_before_network(monkeypatch, tmp_path) -> None:
    configure_completion(monkeypatch, tmp_path)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    exit_code, stdout, stderr = run_cli(
        ["complete", "--text", "x" * 513],
        handler,
    )
    assert exit_code == 2
    assert calls == 0
    assert stdout == ""
    assert "must not exceed 512" in stderr


def test_blank_input_is_rejected_before_network(monkeypatch, tmp_path, caplog) -> None:
    configure_completion(monkeypatch, tmp_path)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    caplog.set_level(logging.WARNING)
    exit_code, stdout, stderr = run_cli(["complete", "--text", " \t"], handler)
    assert exit_code == 2
    assert calls == 0
    assert stdout == ""
    assert "must not be blank" in stderr
    assert "elapsed_seconds=" in caplog.text
    assert "total_tokens=unavailable" in caplog.text


def test_concurrency_limit_is_sanitized_and_makes_no_http_call(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    configure_completion(monkeypatch, tmp_path)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=success_payload())

    class Limited:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def complete(self, _request):
            raise LanguageModelError(
                "sanitized",
                category=CompletionFailureCategory.CONCURRENCY_LIMITED,
                retry_eligible=True,
                queue_wait_seconds=60,
                provider_elapsed_seconds=0,
                attempt_count=0,
            )

    monkeypatch.setattr(ai_cli, "ConcurrencyLimitedLanguageModel", Limited)
    caplog.set_level(logging.WARNING)
    exit_code, stdout, stderr = run_cli(["complete", "--text", "hello"], handler)
    assert exit_code == 5
    assert stdout == ""
    assert "concurrency_limited" in stderr
    assert calls == 0
    assert "queue_wait_seconds=60.000" in caplog.text
    assert "provider_seconds=0.000" in caplog.text
    assert "attempt_count=0" in caplog.text


def test_missing_usage_prints_unavailable(monkeypatch, tmp_path) -> None:
    configure_completion(monkeypatch, tmp_path)
    payload = success_payload()
    payload.pop("usage")
    exit_code, stdout, stderr = run_cli(
        ["complete", "--text", "hello"],
        lambda _: httpx.Response(200, json=payload),
    )
    assert exit_code == 0
    assert "Tokens: unavailable" in stdout
    assert stderr == ""


def test_provider_error_is_sanitized(monkeypatch, tmp_path, caplog) -> None:
    configure_completion(monkeypatch, tmp_path)
    provider_body = f"bad key {API_KEY} at {SERVER_MODEL_PATH} for {PROMPT}"
    caplog.set_level(logging.WARNING)
    exit_code, stdout, stderr = run_cli(
        ["complete", "--text", PROMPT],
        lambda _: httpx.Response(401, json={"error": provider_body}),
    )
    assert exit_code == 5
    assert stdout == ""
    assert "Inference failed: authentication" in stderr
    combined = stderr + caplog.text
    for secret in (API_KEY, provider_body, SERVER_MODEL_PATH, PROMPT):
        assert secret not in combined
    assert "elapsed_seconds=" in caplog.text
    assert "total_tokens=unavailable" in caplog.text


def test_rate_limit_prints_sanitized_retry_delay(monkeypatch, tmp_path) -> None:
    configure_completion(monkeypatch, tmp_path)
    exit_code, stdout, stderr = run_cli(
        ["complete", "--text", "hello"],
        lambda _: httpx.Response(429, headers={"Retry-After": "17"}),
    )
    assert exit_code == 5
    assert stdout == ""
    assert "rate_limited" in stderr
    assert "Retry after: 17s" in stderr


def test_connection_and_timeout_use_existing_exit_codes(monkeypatch, tmp_path) -> None:
    configure_completion(monkeypatch, tmp_path)

    def connection(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    connection_result = run_cli(["complete", "--text", "hello"], connection)
    timeout_result = run_cli(["complete", "--text", "hello"], timeout)
    assert connection_result[0] == 3
    assert "connection" in connection_result[2]
    assert timeout_result[0] == 4
    assert "timeout" in timeout_result[2]
