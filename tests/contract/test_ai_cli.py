from __future__ import annotations

import io
import logging

import httpx

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


def test_health_works_while_disabled_and_without_key(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", "/missing/key")
    exit_code, stdout, stderr = run_cli(
        ["health"],
        lambda _: httpx.Response(200, json={"status": "ok"}),
    )
    assert exit_code == 0
    assert "Health: ok" in stdout
    assert "Provider: llama_cpp" in stdout
    assert OPERATION_ID in stdout
    assert stderr == ""


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
    assert OPERATION_ID in stdout
    assert SERVER_MODEL_PATH not in stdout
    assert stderr == ""
    assert PROMPT not in caplog.text
    assert API_KEY not in caplog.text
    assert SERVER_MODEL_PATH not in caplog.text
    assert "outcome=success" in caplog.text


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
