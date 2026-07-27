"""Process-local concurrency limiting for language-model adapters."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModel,
    LanguageModelError,
)
from personal_edge_lab.domain.ai import CompletionRequest, CompletionResult, CompletionTiming


class ConcurrencyLimitedLanguageModel:
    """Queue callers behind a bounded process-local permit."""

    def __init__(
        self,
        delegate: LanguageModel,
        *,
        max_concurrency: int,
        wait_timeout_seconds: float,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if isinstance(max_concurrency, bool) or max_concurrency != 1:
            raise ValueError("max_concurrency must be exactly 1")
        if (
            isinstance(wait_timeout_seconds, bool)
            or not isinstance(wait_timeout_seconds, (int, float))
            or not math.isfinite(float(wait_timeout_seconds))
            or wait_timeout_seconds <= 0
        ):
            raise ValueError("wait_timeout_seconds must be finite and greater than zero")
        self._delegate = delegate
        self._permit = threading.BoundedSemaphore(max_concurrency)
        self._wait_timeout_seconds = float(wait_timeout_seconds)
        self._clock = clock

    def complete(self, request: CompletionRequest) -> CompletionResult:
        started = self._clock()
        acquired = self._permit.acquire(timeout=self._wait_timeout_seconds)
        queue_wait = max(0.0, self._clock() - started)
        if not acquired:
            raise LanguageModelError(
                "local language model concurrency limit reached",
                category=CompletionFailureCategory.CONCURRENCY_LIMITED,
                retry_eligible=True,
                queue_wait_seconds=queue_wait,
                provider_elapsed_seconds=0,
                attempt_count=0,
            )
        try:
            result = self._delegate.complete(request)
        except LanguageModelError as error:
            raise error.with_queue_wait(queue_wait) from error
        finally:
            self._permit.release()
        return replace(
            result,
            timing=CompletionTiming(
                queue_wait_seconds=result.timing.queue_wait_seconds + queue_wait,
                provider_seconds=result.timing.provider_seconds,
            ),
        )
