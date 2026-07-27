"""Local language-model diagnostic CLI composition root."""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModelError,
)
from personal_edge_lab.apps.ai_cli.config import (
    CompletionSettings,
    ConfigurationError,
    HealthSettings,
)
from personal_edge_lab.apps.logging_config import configure_logging
from personal_edge_lab.domain.ai import (
    AiValidationError,
    CompletionRequest,
    ModelMessage,
    ModelRole,
)
from personal_edge_lab.infrastructure.ai.concurrency import ConcurrencyLimitedLanguageModel
from personal_edge_lab.infrastructure.ai.llama_cpp import (
    LlamaCppHealthProbe,
    LlamaCppLanguageModel,
    LlamaCppReadinessProbe,
)

LOGGER = logging.getLogger(__name__)

EXIT_BY_CATEGORY = {
    CompletionFailureCategory.CONNECTION: 3,
    CompletionFailureCategory.TIMEOUT: 4,
    CompletionFailureCategory.AUTHENTICATION: 5,
    CompletionFailureCategory.RATE_LIMITED: 5,
    CompletionFailureCategory.NOT_READY: 5,
    CompletionFailureCategory.REQUEST_REJECTED: 5,
    CompletionFailureCategory.PROVIDER_FAILURE: 5,
    CompletionFailureCategory.INVALID_PROVIDER_RESPONSE: 5,
    CompletionFailureCategory.CONCURRENCY_LIMITED: 5,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m personal_edge_lab.apps.ai_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="check public local-model liveness")
    subparsers.add_parser("ready", help="check public local-model readiness")
    complete_parser = subparsers.add_parser("complete", help="run one bounded completion")
    complete_parser.add_argument("--text", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    transport: Any | None = None,
    operation_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> int:
    args = build_parser().parse_args(argv)
    operation_id = operation_id_factory()
    if args.command == "health":
        return _run_health(
            operation_id,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    if args.command == "ready":
        return _run_ready(
            operation_id,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    return _run_complete(
        operation_id,
        args.text,
        stdout=stdout,
        stderr=stderr,
        transport=transport,
    )


def _run_health(
    operation_id: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    try:
        settings = HealthSettings.from_env()
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    started = time.perf_counter()
    try:
        with LlamaCppHealthProbe(
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            transport=transport,
        ) as probe:
            result = probe.check()
    except LanguageModelError as error:
        return _provider_failure(
            operation_id,
            "health",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    LOGGER.info(
        "local_llm operation_id=%s command=health outcome=success provider=%s "
        "queue_wait_seconds=0.000 provider_seconds=%.3f elapsed_seconds=%.3f attempt_count=1",
        operation_id,
        result.provider,
        result.elapsed_seconds,
        result.elapsed_seconds,
    )
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Health: {result.status}", file=stdout)
    print(f"Provider: {result.provider}", file=stdout)
    print(f"Elapsed: {result.elapsed_seconds:.3f}s", file=stdout)
    return 0


def _run_ready(
    operation_id: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    try:
        settings = HealthSettings.from_env()
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    started = time.perf_counter()
    try:
        with LlamaCppReadinessProbe(
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            transport=transport,
        ) as probe:
            result = probe.check()
    except LanguageModelError as error:
        return _provider_failure(
            operation_id,
            "ready",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    LOGGER.info(
        "local_llm operation_id=%s command=ready outcome=success provider=%s "
        "queue_wait_seconds=0.000 provider_seconds=%.3f elapsed_seconds=%.3f attempt_count=1",
        operation_id,
        result.provider,
        result.elapsed_seconds,
        result.elapsed_seconds,
    )
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Readiness: {result.status}", file=stdout)
    print(f"Provider: {result.provider}", file=stdout)
    print(f"Elapsed: {result.elapsed_seconds:.3f}s", file=stdout)
    return 0


def _run_complete(
    operation_id: str,
    text: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    try:
        settings = CompletionSettings.from_env()
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    started = time.perf_counter()
    if not text.strip():
        return _input_failure(
            operation_id,
            "completion text must not be blank",
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    if len(text) > settings.max_input_chars:
        return _input_failure(
            operation_id,
            f"completion text must not exceed {settings.max_input_chars} characters",
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    try:
        request = CompletionRequest(
            messages=(ModelMessage(role=ModelRole.USER, content=text),),
            model_alias=settings.model_alias,
            max_output_tokens=settings.max_output_tokens,
            temperature=0,
        )
    except AiValidationError as error:
        return _input_failure(
            operation_id,
            str(error),
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    try:
        with LlamaCppLanguageModel(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout_seconds=settings.timeout_seconds,
            transport=transport,
        ) as adapter:
            model = ConcurrencyLimitedLanguageModel(
                adapter,
                max_concurrency=settings.max_concurrency,
                wait_timeout_seconds=settings.queue_timeout_seconds,
            )
            result = model.complete(request)
    except LanguageModelError as error:
        return _provider_failure(
            operation_id,
            "complete",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    usage = result.usage
    LOGGER.info(
        "local_llm operation_id=%s command=complete outcome=success "
        "provider=%s model=%s queue_wait_seconds=%.3f provider_seconds=%.3f "
        "elapsed_seconds=%.3f attempt_count=1 prompt_tokens=%s completion_tokens=%s "
        "total_tokens=%s",
        operation_id,
        result.provider,
        result.model_alias,
        result.timing.queue_wait_seconds,
        result.timing.provider_seconds,
        result.elapsed_seconds,
        usage.prompt_tokens if usage else "unavailable",
        usage.completion_tokens if usage else "unavailable",
        usage.total_tokens if usage else "unavailable",
    )
    print(f"Operation: {operation_id}", file=stdout)
    print("Completion:", file=stdout)
    print(_sanitize_terminal_text(result.text), file=stdout)
    print(f"Provider: {result.provider}", file=stdout)
    print(f"Model: {result.model_alias}", file=stdout)
    if usage is None:
        print("Tokens: unavailable", file=stdout)
    else:
        print(
            f"Tokens: prompt={usage.prompt_tokens} completion={usage.completion_tokens} "
            f"total={usage.total_tokens}",
            file=stdout,
        )
    print(f"Queue wait: {result.timing.queue_wait_seconds:.3f}s", file=stdout)
    print(f"Provider elapsed: {result.timing.provider_seconds:.3f}s", file=stdout)
    print(f"Elapsed: {result.elapsed_seconds:.3f}s", file=stdout)
    return 0


def _configuration_failure(
    operation_id: str,
    error: ConfigurationError,
    *,
    stderr: TextIO,
) -> int:
    print(f"Operation: {operation_id}", file=stderr)
    print(f"Configuration error: {error}", file=stderr)
    return 2


def _input_failure(
    operation_id: str,
    message: str,
    *,
    elapsed_seconds: float,
    stderr: TextIO,
) -> int:
    LOGGER.warning(
        "local_llm operation_id=%s command=complete outcome=failure category=input_validation "
        "queue_wait_seconds=0.000 provider_seconds=0.000 elapsed_seconds=%.3f attempt_count=0 "
        "prompt_tokens=unavailable completion_tokens=unavailable total_tokens=unavailable",
        operation_id,
        elapsed_seconds,
    )
    print(f"Operation: {operation_id}", file=stderr)
    print(f"Input error: {message}", file=stderr)
    return 2


def _provider_failure(
    operation_id: str,
    command: str,
    error: LanguageModelError,
    *,
    elapsed_seconds: float,
    stderr: TextIO,
) -> int:
    LOGGER.warning(
        "local_llm operation_id=%s command=%s outcome=failure category=%s "
        "queue_wait_seconds=%.3f provider_seconds=%s elapsed_seconds=%.3f attempt_count=%s "
        "http_status=%s retry_eligible=%s retry_after_seconds=%s prompt_tokens=unavailable "
        "completion_tokens=unavailable total_tokens=unavailable",
        operation_id,
        command,
        error.category.value,
        error.queue_wait_seconds,
        (
            f"{error.provider_elapsed_seconds:.3f}"
            if error.provider_elapsed_seconds is not None
            else "unavailable"
        ),
        elapsed_seconds,
        error.attempt_count,
        error.http_status,
        error.retry_eligible,
        error.retry_after_seconds,
    )
    print(f"Operation: {operation_id}", file=stderr)
    print(f"Inference failed: {error.category.value}", file=stderr)
    if error.retry_after_seconds is not None:
        print(f"Retry after: {error.retry_after_seconds:g}s", file=stderr)
    return EXIT_BY_CATEGORY[error.category]


def _sanitize_terminal_text(value: str) -> str:
    return "".join(
        character if character.isprintable() or character in "\n\t" else "�" for character in value
    )


if __name__ == "__main__":
    raise SystemExit(main())
