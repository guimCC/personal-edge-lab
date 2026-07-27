from __future__ import annotations

import threading
import time

import pytest

from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModelError,
)
from personal_edge_lab.domain.ai import (
    CompletionRequest,
    CompletionResult,
    CompletionTiming,
    ModelIdentity,
    ModelMessage,
    ModelRole,
)
from personal_edge_lab.infrastructure.ai.concurrency import ConcurrencyLimitedLanguageModel


def request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ModelMessage(ModelRole.USER, "hello"),),
        model_alias="qwen3-1.7b-q4-k-m",
        max_output_tokens=1,
        temperature=0,
    )


def result() -> CompletionResult:
    return CompletionResult(
        text="ready",
        identity=ModelIdentity(provider="llama_cpp", model_alias="qwen3-1.7b-q4-k-m"),
        usage=None,
        timing=CompletionTiming(queue_wait_seconds=0, provider_seconds=0.25),
    )


class BlockingModel:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def complete(self, _request: CompletionRequest) -> CompletionResult:
        with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
        assert self.release.wait(timeout=2)
        with self.lock:
            self.active -= 1
        return result()


def test_second_request_waits_and_only_one_delegate_call_is_active() -> None:
    delegate = BlockingModel()
    model = ConcurrencyLimitedLanguageModel(
        delegate,
        max_concurrency=1,
        wait_timeout_seconds=1,
    )
    results: list[CompletionResult] = []
    second_called = threading.Event()

    first = threading.Thread(target=lambda: results.append(model.complete(request())))

    def run_second() -> None:
        second_called.set()
        results.append(model.complete(request()))

    second = threading.Thread(target=run_second)
    first.start()
    assert delegate.started.wait(timeout=1)
    second.start()
    assert second_called.wait(timeout=1)
    time.sleep(0.02)
    assert delegate.calls == 1
    delegate.release.set()
    first.join(timeout=1)
    second.join(timeout=1)
    assert not first.is_alive()
    assert not second.is_alive()
    assert delegate.calls == 2
    assert delegate.max_active == 1
    assert len(results) == 2
    assert sum(item.timing.queue_wait_seconds >= 0.01 for item in results) == 1


def test_queue_expiry_makes_no_second_delegate_call() -> None:
    delegate = BlockingModel()
    model = ConcurrencyLimitedLanguageModel(
        delegate,
        max_concurrency=1,
        wait_timeout_seconds=0.01,
    )
    first = threading.Thread(target=lambda: model.complete(request()))
    first.start()
    assert delegate.started.wait(timeout=1)
    with pytest.raises(LanguageModelError) as captured:
        model.complete(request())
    assert captured.value.category is CompletionFailureCategory.CONCURRENCY_LIMITED
    assert captured.value.retry_eligible is True
    assert captured.value.attempt_count == 0
    assert captured.value.provider_elapsed_seconds == 0
    assert captured.value.queue_wait_seconds >= 0.01
    assert delegate.calls == 1
    delegate.release.set()
    first.join(timeout=1)
    assert not first.is_alive()


@pytest.mark.parametrize("failure", ["language_model", "unexpected"])
def test_permit_is_released_after_every_delegate_failure(failure: str) -> None:
    class FailingOnceModel:
        calls = 0

        def complete(self, _request: CompletionRequest) -> CompletionResult:
            self.calls += 1
            if self.calls == 1:
                if failure == "language_model":
                    raise LanguageModelError(
                        "sanitized",
                        category=CompletionFailureCategory.PROVIDER_FAILURE,
                        retry_eligible=True,
                        provider_elapsed_seconds=0.1,
                    )
                raise RuntimeError("unexpected")
            return result()

    delegate = FailingOnceModel()
    model = ConcurrencyLimitedLanguageModel(
        delegate,
        max_concurrency=1,
        wait_timeout_seconds=0.1,
    )
    expected = LanguageModelError if failure == "language_model" else RuntimeError
    with pytest.raises(expected):
        model.complete(request())
    assert model.complete(request()).text == "ready"
    assert delegate.calls == 2


def test_limiter_configuration_is_bounded() -> None:
    delegate = BlockingModel()
    with pytest.raises(ValueError, match="exactly 1"):
        ConcurrencyLimitedLanguageModel(
            delegate,
            max_concurrency=2,
            wait_timeout_seconds=1,
        )
    with pytest.raises(ValueError, match="greater than zero"):
        ConcurrencyLimitedLanguageModel(
            delegate,
            max_concurrency=1,
            wait_timeout_seconds=0,
        )
