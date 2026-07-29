"""Local language-model diagnostic CLI composition root."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from importlib.resources import files
from typing import Any, TextIO

from personal_edge_lab import __version__
from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModelError,
)
from personal_edge_lab.application.ports.email_triage import NoOpTriageTraceSink
from personal_edge_lab.apps.ai_cli.config import (
    CompletionSettings,
    ConfigurationError,
    HealthSettings,
    LangfuseSettings,
    TriageSettings,
)
from personal_edge_lab.apps.logging_config import configure_logging
from personal_edge_lab.domain.ai import (
    AiValidationError,
    CompletionRequest,
    ModelMessage,
    ModelRole,
)
from personal_edge_lab.domain.email_triage import TriageEmail, TriageLabel, TriageOutputError
from personal_edge_lab.infrastructure.ai.concurrency import ConcurrencyLimitedLanguageModel
from personal_edge_lab.infrastructure.ai.llama_cpp import (
    LlamaCppHealthProbe,
    LlamaCppLanguageModel,
    LlamaCppReadinessProbe,
)
from personal_edge_lab.infrastructure.ai.triage_decoder import PydanticTriageDecisionDecoder
from personal_edge_lab.infrastructure.observability.langfuse import (
    LangfuseTriageRuntime,
)
from personal_edge_lab.modules.email_triage import EmailTriageService
from personal_edge_lab.modules.email_triage.prompt import (
    LocalTriagePromptSource,
    load_packaged_prompt,
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
    triage_parser = subparsers.add_parser("triage", help="classify one synthetic email fixture")
    triage_parser.add_argument("--fixture", required=True, choices=("synthetic-invoice",))
    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="run the checked-in synthetic taxonomy baseline without tracing",
    )
    evaluate_parser.add_argument(
        "--fixture-set",
        required=True,
        choices=("taxonomy-v2-core",),
    )
    subparsers.add_parser(
        "prompt-publish",
        help="publish the packaged email-triage prompt to Langfuse",
    )
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
    if args.command == "complete":
        return _run_complete(
            operation_id,
            args.text,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    if args.command == "triage":
        return _run_triage(
            operation_id,
            args.fixture,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    if args.command == "evaluate":
        return _run_evaluate(
            operation_id,
            args.fixture_set,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    return _run_prompt_publish(operation_id, stdout=stdout, stderr=stderr)


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


def _run_triage(
    operation_id: str,
    fixture_name: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    try:
        settings = TriageSettings.from_env()
        email = _load_fixture(fixture_name)
    except (ConfigurationError, ValueError) as error:
        return _configuration_failure(
            operation_id,
            ConfigurationError(str(error)),
            stderr=stderr,
        )
    configure_logging(settings.completion.log_level)
    started = time.perf_counter()
    manifest = load_packaged_prompt()
    runtime: LangfuseTriageRuntime | None = None
    prompt_source = LocalTriagePromptSource(manifest)
    trace_sink: Any = NoOpTriageTraceSink()
    if settings.langfuse.enabled:
        assert settings.langfuse.public_key is not None
        assert settings.langfuse.secret_key is not None
        try:
            runtime = LangfuseTriageRuntime(
                public_key=settings.langfuse.public_key,
                secret_key=settings.langfuse.secret_key,
                base_url=settings.langfuse.base_url,
                timeout_seconds=settings.langfuse.timeout_seconds,
                release=__version__,
                manifest=manifest,
            )
        except Exception:
            LOGGER.warning(
                "email_triage operation_id=%s command=triage trace_unavailable=true",
                operation_id,
            )
        else:
            prompt_source = runtime
            trace_sink = runtime
    try:
        with LlamaCppLanguageModel(
            base_url=settings.completion.base_url,
            api_key=settings.completion.api_key,
            timeout_seconds=settings.completion.timeout_seconds,
            transport=transport,
        ) as adapter:
            model = ConcurrencyLimitedLanguageModel(
                adapter,
                max_concurrency=settings.completion.max_concurrency,
                wait_timeout_seconds=settings.completion.queue_timeout_seconds,
            )
            result = EmailTriageService(
                model=model,
                prompt_source=prompt_source,
                decoder=PydanticTriageDecisionDecoder(),
                trace_sink=trace_sink,
                model_alias=settings.completion.model_alias,
            ).classify(email, operation_id=operation_id)
    except LanguageModelError as error:
        return _provider_failure(
            operation_id,
            "triage",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    except TriageOutputError:
        elapsed = time.perf_counter() - started
        LOGGER.warning(
            "email_triage operation_id=%s command=triage outcome=failure "
            "category=triage_output elapsed_seconds=%.3f trace_unavailable=%s",
            operation_id,
            elapsed,
            not settings.langfuse.enabled,
        )
        print(f"Operation: {operation_id}", file=stderr)
        print("Triage failed: invalid_model_output", file=stderr)
        return 5
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                LOGGER.warning(
                    "email_triage operation_id=%s command=triage trace_unavailable=true",
                    operation_id,
                )
    completion = result.evidence.completion
    usage = completion.usage
    LOGGER.info(
        "email_triage operation_id=%s command=triage outcome=success "
        "provider=%s model=%s prompt_source=%s prompt_version=%s "
        "queue_wait_seconds=%.3f provider_seconds=%.3f elapsed_seconds=%.3f "
        "attempt_count=1 prompt_tokens=%s completion_tokens=%s total_tokens=%s "
        "trace_unavailable=%s",
        operation_id,
        completion.provider,
        completion.model_alias,
        result.evidence.prompt.source.value,
        result.evidence.prompt.version,
        completion.timing.queue_wait_seconds,
        completion.timing.provider_seconds,
        completion.elapsed_seconds,
        usage.prompt_tokens if usage else "unavailable",
        usage.completion_tokens if usage else "unavailable",
        usage.total_tokens if usage else "unavailable",
        result.evidence.trace_unavailable,
    )
    assert result.decision.reason is not None
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Label: {result.decision.label.value}", file=stdout)
    print(f"Reason: {_sanitize_terminal_text(result.decision.reason)}", file=stdout)
    print(f"Prompt source: {result.evidence.prompt.source.value}", file=stdout)
    print(f"Prompt version: {result.evidence.prompt.version}", file=stdout)
    print(f"Trace: {result.evidence.trace_id or 'unavailable'}", file=stdout)
    print(f"Provider: {completion.provider}", file=stdout)
    print(f"Model: {completion.model_alias}", file=stdout)
    if usage:
        print(
            f"Tokens: prompt={usage.prompt_tokens} completion={usage.completion_tokens} "
            f"total={usage.total_tokens}",
            file=stdout,
        )
    else:
        print("Tokens: unavailable", file=stdout)
    print(f"Queue wait: {completion.timing.queue_wait_seconds:.3f}s", file=stdout)
    print(f"Provider elapsed: {completion.timing.provider_seconds:.3f}s", file=stdout)
    print(f"Elapsed: {completion.elapsed_seconds:.3f}s", file=stdout)
    return 0


def _run_prompt_publish(operation_id: str, *, stdout: TextIO, stderr: TextIO) -> int:
    try:
        settings = LangfuseSettings.from_env(require_enabled=True)
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    assert settings.public_key is not None
    assert settings.secret_key is not None
    runtime: LangfuseTriageRuntime | None = None
    try:
        runtime = LangfuseTriageRuntime(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            release=__version__,
            manifest=load_packaged_prompt(),
        )
        outcome, version = runtime.publish_packaged_prompt()
    except Exception:
        LOGGER.warning(
            "email_triage operation_id=%s command=prompt-publish outcome=failure "
            "category=provider_failure",
            operation_id,
        )
        print(f"Operation: {operation_id}", file=stderr)
        print("Prompt publication failed: provider_failure", file=stderr)
        return 5
    finally:
        if runtime is not None:
            with suppress(Exception):
                runtime.close()
    print(f"Operation: {operation_id}", file=stdout)
    print("Prompt: personal-edge-lab/email-triage", file=stdout)
    print(f"Outcome: {outcome}", file=stdout)
    print(f"Version: {version}", file=stdout)
    LOGGER.info(
        "email_triage operation_id=%s command=prompt-publish outcome=%s prompt_version=%s",
        operation_id,
        outcome,
        version,
    )
    return 0


def _run_evaluate(
    operation_id: str,
    fixture_set: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    try:
        settings = CompletionSettings.from_env()
        fixtures = _load_fixture_set(fixture_set)
    except (ConfigurationError, ValueError) as error:
        return _configuration_failure(
            operation_id,
            ConfigurationError(str(error)),
            stderr=stderr,
        )
    configure_logging(settings.log_level)
    correct = 0
    results: list[tuple[str, TriageLabel, TriageLabel]] = []
    started = time.perf_counter()
    try:
        with LlamaCppLanguageModel(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout_seconds=settings.timeout_seconds,
            transport=transport,
        ) as adapter:
            service = EmailTriageService(
                model=ConcurrencyLimitedLanguageModel(
                    adapter,
                    max_concurrency=settings.max_concurrency,
                    wait_timeout_seconds=settings.queue_timeout_seconds,
                ),
                prompt_source=LocalTriagePromptSource(load_packaged_prompt()),
                decoder=PydanticTriageDecisionDecoder(),
                trace_sink=NoOpTriageTraceSink(),
                model_alias=settings.model_alias,
            )
            for index, (fixture_id, expected, email) in enumerate(fixtures, start=1):
                result = service.classify(
                    email,
                    operation_id=f"{operation_id}-{index}",
                )
                results.append((fixture_id, expected, result.decision.label))
                correct += result.decision.label is expected
    except LanguageModelError as error:
        return _provider_failure(
            operation_id,
            "evaluate",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    except TriageOutputError:
        print(f"Operation: {operation_id}", file=stderr)
        print("Evaluation failed: invalid_model_output", file=stderr)
        return 5
    elapsed = time.perf_counter() - started
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Fixture set: {fixture_set}", file=stdout)
    for fixture_id, expected, actual in results:
        outcome = "match" if expected is actual else "different"
        print(
            f"{fixture_id}: expected={expected.value} actual={actual.value} {outcome}",
            file=stdout,
        )
    print(f"Baseline: {correct}/{len(results)}", file=stdout)
    print("Quality threshold: none", file=stdout)
    print("Traces: none", file=stdout)
    print(f"Elapsed: {elapsed:.3f}s", file=stdout)
    LOGGER.info(
        "email_triage operation_id=%s command=evaluate outcome=success "
        "fixture_set=%s fixture_count=%d match_count=%d elapsed_seconds=%.3f",
        operation_id,
        fixture_set,
        len(results),
        correct,
        elapsed,
    )
    return 0


def _load_fixture(name: str) -> TriageEmail:
    resource = files("personal_edge_lab.apps.ai_cli.fixtures").joinpath(f"{name}.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"sender", "subject", "message"}:
        raise ValueError("synthetic fixture is invalid")
    return TriageEmail(
        sender=payload["sender"],
        subject=payload["subject"],
        message=payload["message"],
    )


def _load_fixture_set(name: str) -> tuple[tuple[str, TriageLabel, TriageEmail], ...]:
    resource = files("personal_edge_lab.apps.ai_cli.fixtures").joinpath(f"{name}.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not 1 <= len(payload) <= 20:
        raise ValueError("synthetic fixture set is invalid")
    fixtures: list[tuple[str, TriageLabel, TriageEmail]] = []
    for entry in payload:
        if not isinstance(entry, dict) or set(entry) != {
            "id",
            "expected_label",
            "sender",
            "subject",
            "message",
        }:
            raise ValueError("synthetic fixture set is invalid")
        try:
            expected = TriageLabel(entry["expected_label"])
            email = TriageEmail(
                sender=entry["sender"],
                subject=entry["subject"],
                message=entry["message"],
            )
        except (TypeError, ValueError) as error:
            raise ValueError("synthetic fixture set is invalid") from error
        fixture_id = entry["id"]
        if expected.is_legacy or not isinstance(fixture_id, str) or not fixture_id:
            raise ValueError("synthetic fixture set is invalid")
        fixtures.append((fixture_id, expected, email))
    return tuple(fixtures)


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
