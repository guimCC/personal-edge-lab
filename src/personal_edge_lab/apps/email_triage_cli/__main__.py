"""Composition root for bounded read-only Gmail diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import signal
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any, TextIO

from personal_edge_lab import __version__
from personal_edge_lab.application.ports.email import (
    EmailSource,
    EmailSourceError,
    EmailSourceFailureCategory,
)
from personal_edge_lab.application.ports.email_triage import NoOpTriageTraceSink
from personal_edge_lab.apps.email_triage_cli.config import (
    BackfillSettings,
    ConfigurationError,
    GmailAuthorizationSettings,
    GmailFetchSettings,
    MailboxTriageSettings,
    TriageHistorySettings,
    read_triage_rules,
)
from personal_edge_lab.apps.logging_config import configure_logging
from personal_edge_lab.domain.email import EmailRetrievalRequest, EmailValidationError
from personal_edge_lab.domain.email_triage_backfill import (
    BACKFILL_MONTHS,
    TriageBackfillJob,
    TriageBackfillStatus,
    TriageBackfillValidationError,
    validate_backfill_step_items,
)
from personal_edge_lab.domain.email_triage_runs import (
    MailboxTriageResult,
    TriageRunStatus,
    TriageRunValidationError,
    validate_recent_run_limit,
)
from personal_edge_lab.infrastructure.ai.concurrency import ConcurrencyLimitedLanguageModel
from personal_edge_lab.infrastructure.ai.llama_cpp import LlamaCppLanguageModel
from personal_edge_lab.infrastructure.ai.triage_decoder import PydanticTriageDecisionDecoder
from personal_edge_lab.infrastructure.gmail.client import GmailEmailSource
from personal_edge_lab.infrastructure.gmail.oauth import (
    GMAIL_READONLY_SCOPE,
    GoogleOAuthCredentialStore,
    authorize_google_oauth,
)
from personal_edge_lab.infrastructure.observability.langfuse import LangfuseTriageRuntime
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage import (
    SqliteTriageRunRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage_backfill import (
    SqliteTriageBackfillRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage_reset import (
    RESET_CONFIRMATION,
    TriageDevelopmentResetError,
    reset_triage_development_data,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.email_triage import (
    EmailTriageService,
    TriageHistoricalBackfill,
    TriageMailboxBatch,
)
from personal_edge_lab.modules.email_triage.backfill import backfill_segments
from personal_edge_lab.modules.email_triage.prompt import (
    LocalTriagePromptSource,
    load_packaged_prompt,
)

LOGGER = logging.getLogger(__name__)

EXIT_BY_CATEGORY = {
    EmailSourceFailureCategory.CONNECTION: 3,
    EmailSourceFailureCategory.TIMEOUT: 4,
    EmailSourceFailureCategory.AUTHENTICATION: 5,
    EmailSourceFailureCategory.PERMISSION_DENIED: 5,
    EmailSourceFailureCategory.RATE_LIMITED: 5,
    EmailSourceFailureCategory.SOURCE_UNAVAILABLE: 5,
    EmailSourceFailureCategory.INVALID_RESPONSE: 5,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m personal_edge_lab.apps.email_triage_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    authorize_parser = subparsers.add_parser(
        "authorize",
        help="authorize one personal Gmail account with read-only scope",
    )
    authorize_parser.add_argument("--replace-token", action="store_true")
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="retrieve one bounded read-only Gmail batch",
    )
    fetch_parser.add_argument("--query", required=True)
    fetch_parser.add_argument("--limit", type=int)
    triage_parser = subparsers.add_parser(
        "triage",
        help="run one bounded read-only Gmail-to-model dry run",
    )
    triage_parser.add_argument("--query", required=True)
    triage_parser.add_argument("--limit", required=True, type=int)
    triage_parser.add_argument("--new-attempt", action="store_true")
    runs_parser = subparsers.add_parser("runs", help="show recent durable triage runs")
    runs_parser.add_argument("--limit", type=int, default=20)
    show_parser = subparsers.add_parser("show", help="show one durable triage run")
    show_parser.add_argument("--run-id", required=True)
    reset_parser = subparsers.add_parser(
        "reset-development-data",
        help="back up and delete only disposable email-triage development records",
    )
    reset_parser.add_argument("--confirm", required=True)
    subparsers.add_parser(
        "rules-check",
        help="validate the optional private deterministic sender rules",
    )
    backfill_start = subparsers.add_parser(
        "backfill-start",
        help="create one fixed twelve-month historical backfill",
    )
    backfill_start.add_argument("--months", type=int, default=BACKFILL_MONTHS)
    backfill_run = subparsers.add_parser(
        "backfill-run",
        help="discover one page and process one bounded backfill step",
    )
    backfill_run.add_argument("--job-id", required=True)
    backfill_run.add_argument("--max-items", type=int, default=10)
    backfill_run.add_argument("--retry-failures", action="store_true")
    backfill_status = subparsers.add_parser(
        "backfill-status",
        help="show durable historical-backfill progress",
    )
    backfill_status.add_argument("--job-id")
    backfill_status.add_argument("--limit", type=int, default=5)
    backfill_cancel = subparsers.add_parser(
        "backfill-cancel",
        help="cancel one historical backfill without deleting evidence",
    )
    backfill_cancel.add_argument("--job-id", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    transport: Any | None = None,
    operation_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    authorization_runner: Callable[..., None] = authorize_google_oauth,
) -> int:
    args = build_parser().parse_args(argv)
    operation_id = operation_id_factory()
    if args.command == "authorize":
        return _run_authorize(
            operation_id,
            replace_token=args.replace_token,
            stdout=stdout,
            stderr=stderr,
            authorization_runner=authorization_runner,
        )
    if args.command == "fetch":
        return _run_fetch(
            operation_id,
            query=args.query,
            requested_limit=args.limit,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    if args.command == "triage":
        return _run_triage_mailbox(
            operation_id,
            query=args.query,
            limit=args.limit,
            force_new_attempt=args.new_attempt,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    if args.command == "runs":
        return _run_history(operation_id, args.limit, stdout=stdout, stderr=stderr)
    if args.command == "show":
        return _show_run(operation_id, args.run_id, stdout=stdout, stderr=stderr)
    if args.command == "rules-check":
        return _run_rules_check(operation_id, stdout=stdout, stderr=stderr)
    if args.command == "backfill-start":
        return _run_backfill_start(
            operation_id,
            months=args.months,
            stdout=stdout,
            stderr=stderr,
        )
    if args.command == "backfill-run":
        return _run_backfill_step(
            operation_id,
            job_id=args.job_id,
            max_items=args.max_items,
            retry_failures=args.retry_failures,
            stdout=stdout,
            stderr=stderr,
            transport=transport,
        )
    if args.command == "backfill-status":
        return _run_backfill_status(
            operation_id,
            job_id=args.job_id,
            limit=args.limit,
            stdout=stdout,
            stderr=stderr,
        )
    if args.command == "backfill-cancel":
        return _run_backfill_cancel(
            operation_id,
            job_id=args.job_id,
            stdout=stdout,
            stderr=stderr,
        )
    return _run_development_reset(
        operation_id,
        confirmation=args.confirm,
        stdout=stdout,
        stderr=stderr,
    )


def _run_authorize(
    operation_id: str,
    *,
    replace_token: bool,
    stdout: TextIO,
    stderr: TextIO,
    authorization_runner: Callable[..., None],
) -> int:
    try:
        settings = GmailAuthorizationSettings.from_env()
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    started = time.perf_counter()
    try:
        authorization_runner(
            client_secret_file=settings.client_secret_file,
            token_file=settings.token_file,
            callback_port=settings.callback_port,
            replace_token=replace_token,
        )
    except EmailSourceError as error:
        return _source_failure(
            operation_id,
            "authorize",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    elapsed = time.perf_counter() - started
    LOGGER.info(
        "gmail_read operation_id=%s command=authorize outcome=success "
        "elapsed_seconds=%.3f api_call_count=0",
        operation_id,
        elapsed,
    )
    print(f"Operation: {operation_id}", file=stdout)
    print("Authorization: success", file=stdout)
    print(f"Scope: {GMAIL_READONLY_SCOPE}", file=stdout)
    print(f"Elapsed: {elapsed:.3f}s", file=stdout)
    return 0


def _run_fetch(
    operation_id: str,
    *,
    query: str,
    requested_limit: int | None,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    try:
        settings = GmailFetchSettings.from_env()
        request = EmailRetrievalRequest(
            query=query,
            limit=(requested_limit if requested_limit is not None else settings.default_batch_size),
        )
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    except EmailValidationError as error:
        return _input_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    started = time.perf_counter()
    try:
        credentials = GoogleOAuthCredentialStore(
            token_file=settings.token_file,
            timeout_seconds=settings.timeout_seconds,
        )
        with GmailEmailSource(
            credentials=credentials,
            timeout_seconds=settings.timeout_seconds,
            max_message_bytes=settings.max_message_bytes,
            max_normalized_chars=settings.max_normalized_chars,
            transport=transport,
        ) as source:
            batch = source.retrieve(request)
    except EmailSourceError as error:
        return _source_failure(
            operation_id,
            "fetch",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
            query=query,
        )

    elapsed = time.perf_counter() - started
    outcome = "partial_failure" if batch.failures else "success"
    LOGGER.log(
        logging.WARNING if batch.failures else logging.INFO,
        "gmail_read operation_id=%s command=fetch outcome=%s category=%s "
        "query_sha256=%s document_count=%s failure_count=%s pages_fetched=%s "
        "api_call_count=%s elapsed_seconds=%.3f",
        operation_id,
        outcome,
        "message_protocol" if batch.failures else "none",
        _query_hash(query),
        len(batch.documents),
        len(batch.failures),
        batch.pages_fetched,
        batch.api_call_count,
        elapsed,
    )
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Messages: {len(batch.documents)}", file=stdout)
    print(f"Failures: {len(batch.failures)}", file=stdout)
    print(f"More available: {'yes' if batch.has_more else 'no'}", file=stdout)
    for index, document in enumerate(batch.documents, start=1):
        print(f"Message {index}:", file=stdout)
        print(f"  Received: {document.received_at.isoformat()}", file=stdout)
        print(f"  Message ID: {_sanitize_terminal_text(document.message_id.value)}", file=stdout)
        print(f"  Thread ID: {_sanitize_terminal_text(document.thread_id.value)}", file=stdout)
        print(f"  Sender: {_sanitize_terminal_text(document.sender)}", file=stdout)
        print(f"  Subject: {_sanitize_terminal_text(document.subject)}", file=stdout)
        print(f"  Content source: {document.content_source.value}", file=stdout)
        print(f"  Original bytes: {document.original_size_bytes}", file=stdout)
        print(f"  Normalized characters: {document.normalized_char_count}", file=stdout)
        print(f"  Truncated: {_yes_no(document.truncated)}", file=stdout)
        print(f"  Metadata truncated: {_yes_no(document.metadata_truncated)}", file=stdout)
        print(f"  Quoted text removed: {_yes_no(document.quoted_text_removed)}", file=stdout)
        print(f"  Signature removed: {_yes_no(document.signature_removed)}", file=stdout)
        print(f"  Tracking removed: {_yes_no(document.tracking_removed)}", file=stdout)
        print(
            f"  Duplicate lines removed: {_yes_no(document.duplicate_lines_removed)}",
            file=stdout,
        )
    for failure in batch.failures:
        print(f"Message failure: {failure.category.value}", file=stdout)
    print(f"Elapsed: {elapsed:.3f}s", file=stdout)
    return 5 if batch.failures else 0


def _run_triage_mailbox(
    operation_id: str,
    *,
    query: str,
    limit: int,
    force_new_attempt: bool,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    try:
        settings = MailboxTriageSettings.from_env()
        request = EmailRetrievalRequest(query=query, limit=limit)
        if limit > 10:
            raise EmailValidationError("mailbox triage limit must be from 1 through 10")
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    except EmailValidationError as error:
        return _input_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    try:
        run_migrations(settings.database_path)
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "triage", stderr=stderr)

    interrupted = Event()
    prior_handlers: dict[int, Any] = {}

    def request_interruption(_signum: int, _frame: object) -> None:
        interrupted.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        prior_handlers[signal_number] = signal.getsignal(signal_number)
        signal.signal(signal_number, request_interruption)

    runtime: LangfuseTriageRuntime | None = None
    manifest = load_packaged_prompt()
    prompt_source: Any = LocalTriagePromptSource(manifest)
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

    started = time.perf_counter()
    try:
        credentials = GoogleOAuthCredentialStore(
            token_file=settings.gmail.token_file,
            timeout_seconds=settings.gmail.timeout_seconds,
        )
        with (
            GmailEmailSource(
                credentials=credentials,
                timeout_seconds=settings.gmail.timeout_seconds,
                max_message_bytes=settings.gmail.max_message_bytes,
                max_normalized_chars=settings.gmail.max_normalized_chars,
                transport=transport,
            ) as source,
            LlamaCppLanguageModel(
                base_url=settings.completion.base_url,
                api_key=settings.completion.api_key,
                timeout_seconds=settings.completion.timeout_seconds,
                transport=transport,
            ) as adapter,
            SqliteTriageRunRepository(settings.database_path) as repository,
        ):
            model = ConcurrencyLimitedLanguageModel(
                adapter,
                max_concurrency=settings.completion.max_concurrency,
                wait_timeout_seconds=settings.completion.queue_timeout_seconds,
            )
            service = EmailTriageService(
                model=model,
                prompt_source=prompt_source,
                decoder=PydanticTriageDecisionDecoder(),
                trace_sink=trace_sink,
                model_alias=settings.completion.model_alias,
            )
            result = TriageMailboxBatch(
                email_source=source,
                triage_service=service,
                repository=repository,
                interrupted=interrupted.is_set,
                rules=settings.rules,
            ).execute(
                request,
                run_id=operation_id,
                operation_id=operation_id,
                force_new_attempt=force_new_attempt,
            )
    except EmailSourceError as error:
        return _source_failure(
            operation_id,
            "triage",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
            query=query,
        )
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "triage", stderr=stderr)
    except (TriageRunValidationError, ValueError):
        return _triage_protocol_failure(operation_id, stderr=stderr)
    finally:
        for signal_number, handler in prior_handlers.items():
            signal.signal(signal_number, handler)
        if runtime is not None:
            with suppress(Exception):
                runtime.close()

    _log_triage_result(operation_id, result)
    _print_triage_result(result, stdout=stdout)
    return 0 if result.status is TriageRunStatus.COMPLETED_WITH_RESULTS else 5


def _run_backfill_start(
    operation_id: str,
    *,
    months: int,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        settings = BackfillSettings.from_env()
        if months != BACKFILL_MONTHS:
            raise TriageBackfillValidationError("historical backfill is fixed to exactly 12 months")
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    except TriageBackfillValidationError as error:
        return _input_failure(
            operation_id,
            EmailValidationError(str(error)),
            stderr=stderr,
        )
    configure_logging(settings.triage.log_level)
    cutoff = _utc_now()
    segments = backfill_segments(cutoff)
    try:
        run_migrations(settings.triage.database_path)
        with SqliteTriageBackfillRepository(settings.triage.database_path) as repository:
            repository.create_job(
                job_id=operation_id,
                starts_at=segments[-1][0],
                ends_at=cutoff,
                max_messages=settings.max_messages,
                segments=segments,
                created_at=cutoff,
            )
            job = repository.get_job(operation_id)
    except sqlite3.IntegrityError:
        print(f"Operation: {operation_id}", file=stderr)
        print("Backfill start refused: another historical backfill is active", file=stderr)
        return 5
    except (OSError, sqlite3.Error, ValueError):
        return _persistence_failure(operation_id, "backfill-start", stderr=stderr)
    assert job is not None
    LOGGER.info(
        "email_triage operation_id=%s job_id=%s command=backfill-start "
        "outcome=success months=12 max_messages=%s",
        operation_id,
        job.job_id,
        job.max_messages,
    )
    _print_backfill_job(job, stdout=stdout)
    print("Next: run a bounded step with backfill-run", file=stdout)
    return 0


def _run_backfill_step(
    operation_id: str,
    *,
    job_id: str,
    max_items: int,
    retry_failures: bool,
    stdout: TextIO,
    stderr: TextIO,
    transport: Any | None,
) -> int:
    if not _valid_backfill_id(job_id):
        return _input_failure(
            operation_id,
            EmailValidationError("backfill job ID is invalid"),
            stderr=stderr,
        )
    try:
        settings = BackfillSettings.from_env()
        validate_backfill_step_items(max_items)
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    except TriageBackfillValidationError as error:
        return _input_failure(
            operation_id,
            EmailValidationError(str(error)),
            stderr=stderr,
        )
    configure_logging(settings.triage.log_level)
    try:
        run_migrations(settings.triage.database_path)
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "backfill-run", stderr=stderr)

    interrupted = Event()
    prior_handlers: dict[int, Any] = {}

    def request_interruption(_signum: int, _frame: object) -> None:
        interrupted.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        prior_handlers[signal_number] = signal.getsignal(signal_number)
        signal.signal(signal_number, request_interruption)

    runtime: LangfuseTriageRuntime | None = None
    manifest = load_packaged_prompt()
    prompt_source: Any = LocalTriagePromptSource(manifest)
    trace_sink: Any = NoOpTriageTraceSink()
    if settings.triage.langfuse.enabled:
        assert settings.triage.langfuse.public_key is not None
        assert settings.triage.langfuse.secret_key is not None
        try:
            runtime = LangfuseTriageRuntime(
                public_key=settings.triage.langfuse.public_key,
                secret_key=settings.triage.langfuse.secret_key,
                base_url=settings.triage.langfuse.base_url,
                timeout_seconds=settings.triage.langfuse.timeout_seconds,
                release=__version__,
                manifest=manifest,
            )
        except Exception:
            LOGGER.warning(
                "email_triage operation_id=%s job_id=%s command=backfill-run "
                "trace_unavailable=true",
                operation_id,
                job_id,
            )
        else:
            prompt_source = runtime
            trace_sink = runtime

    started = time.perf_counter()
    try:
        credentials = GoogleOAuthCredentialStore(
            token_file=settings.triage.gmail.token_file,
            timeout_seconds=settings.triage.gmail.timeout_seconds,
        )
        with (
            GmailEmailSource(
                credentials=credentials,
                timeout_seconds=settings.triage.gmail.timeout_seconds,
                max_message_bytes=settings.triage.gmail.max_message_bytes,
                max_normalized_chars=settings.triage.gmail.max_normalized_chars,
                transport=transport,
            ) as source,
            LlamaCppLanguageModel(
                base_url=settings.triage.completion.base_url,
                api_key=settings.triage.completion.api_key,
                timeout_seconds=settings.triage.completion.timeout_seconds,
                transport=transport,
            ) as adapter,
            SqliteTriageRunRepository(settings.triage.database_path) as run_repository,
            SqliteTriageBackfillRepository(settings.triage.database_path) as backfill_repository,
        ):
            model = ConcurrencyLimitedLanguageModel(
                adapter,
                max_concurrency=settings.triage.completion.max_concurrency,
                wait_timeout_seconds=settings.triage.completion.queue_timeout_seconds,
            )
            service = EmailTriageService(
                model=model,
                prompt_source=prompt_source,
                decoder=PydanticTriageDecisionDecoder(),
                trace_sink=trace_sink,
                model_alias=settings.triage.completion.model_alias,
            )

            def batch_factory(email_source: EmailSource) -> TriageMailboxBatch:
                return TriageMailboxBatch(
                    email_source=email_source,
                    triage_service=service,
                    repository=run_repository,
                    interrupted=interrupted.is_set,
                    rules=settings.triage.rules,
                )

            result = TriageHistoricalBackfill(
                email_source=source,
                repository=backfill_repository,
                batch_factory=batch_factory,
                interrupted=interrupted.is_set,
            ).step(
                job_id=job_id,
                max_items=max_items,
                retry_failures=retry_failures,
            )
    except EmailSourceError as error:
        return _source_failure(
            operation_id,
            "backfill-run",
            error,
            elapsed_seconds=time.perf_counter() - started,
            stderr=stderr,
        )
    except LookupError:
        print(f"Operation: {operation_id}", file=stderr)
        print("Historical backfill not found", file=stderr)
        return 5
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "backfill-run", stderr=stderr)
    except (TriageRunValidationError, TriageBackfillValidationError, ValueError):
        return _triage_protocol_failure(operation_id, stderr=stderr)
    finally:
        for signal_number, handler in prior_handlers.items():
            signal.signal(signal_number, handler)
        if runtime is not None:
            with suppress(Exception):
                runtime.close()

    LOGGER.log(
        logging.WARNING if result.job.failed_count or interrupted.is_set() else logging.INFO,
        "email_triage operation_id=%s job_id=%s command=backfill-run outcome=%s "
        "discovered_now=%s processed_now=%s discovered_total=%s pending=%s "
        "succeeded=%s reused=%s failed=%s interrupted=%s active_segment=%s "
        "api_call_count=%s elapsed_seconds=%.3f",
        operation_id,
        job_id,
        result.job.status.value,
        result.discovered_now,
        result.processed_now,
        result.job.discovered_count,
        result.job.pending_count,
        result.job.succeeded_count,
        result.job.reused_count,
        result.job.failed_count,
        result.job.interrupted_count,
        result.job.active_segment or "none",
        result.api_call_count,
        result.elapsed_seconds,
    )
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Discovered this step: {result.discovered_now}", file=stdout)
    print(f"Processed this step: {result.processed_now}", file=stdout)
    print(f"Gmail API calls: {result.api_call_count}", file=stdout)
    print(f"Child runs: {len(result.child_run_ids)}", file=stdout)
    print(f"Elapsed: {result.elapsed_seconds:.3f}s", file=stdout)
    _print_backfill_job(result.job, stdout=stdout)
    print("Gmail changes: none", file=stdout)
    return (
        5
        if interrupted.is_set() or result.job.status is TriageBackfillStatus.COMPLETED_WITH_FAILURES
        else 0
    )


def _run_backfill_status(
    operation_id: str,
    *,
    job_id: str | None,
    limit: int,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if job_id is not None and not _valid_backfill_id(job_id):
        return _input_failure(
            operation_id,
            EmailValidationError("backfill job ID is invalid"),
            stderr=stderr,
        )
    if not 1 <= limit <= 100:
        return _input_failure(
            operation_id,
            EmailValidationError("backfill status limit must be from 1 through 100"),
            stderr=stderr,
        )
    try:
        settings = TriageHistorySettings.from_env()
        configure_logging(settings.log_level)
        run_migrations(settings.database_path)
        with SqliteTriageBackfillRepository(settings.database_path) as repository:
            jobs = (
                ([value] if (value := repository.get_job(job_id)) is not None else [])
                if job_id is not None
                else repository.recent_jobs(limit=limit)
            )
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    except (OSError, sqlite3.Error, ValueError):
        return _persistence_failure(operation_id, "backfill-status", stderr=stderr)
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Backfills: {len(jobs)}", file=stdout)
    for job in jobs:
        _print_backfill_job(job, stdout=stdout)
    return 0 if jobs or job_id is None else 5


def _run_backfill_cancel(
    operation_id: str,
    *,
    job_id: str,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if not _valid_backfill_id(job_id):
        return _input_failure(
            operation_id,
            EmailValidationError("backfill job ID is invalid"),
            stderr=stderr,
        )
    try:
        settings = BackfillSettings.from_env()
        configure_logging(settings.triage.log_level)
        run_migrations(settings.triage.database_path)
        with SqliteTriageBackfillRepository(settings.triage.database_path) as repository:
            repository.cancel_job(job_id, updated_at=_utc_now())
            job = repository.get_job(job_id)
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    except LookupError:
        print(f"Operation: {operation_id}\nBackfill cancellation refused", file=stderr)
        return 5
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "backfill-cancel", stderr=stderr)
    assert job is not None
    LOGGER.warning(
        "email_triage operation_id=%s job_id=%s command=backfill-cancel outcome=success",
        operation_id,
        job_id,
    )
    _print_backfill_job(job, stdout=stdout)
    return 0


def _print_backfill_job(job: TriageBackfillJob, *, stdout: TextIO) -> None:
    print(f"Backfill: {job.job_id}", file=stdout)
    print(f"Status: {job.status.value}", file=stdout)
    print(f"Range: {job.starts_at.isoformat()} to {job.ends_at.isoformat()}", file=stdout)
    print(f"Discovered: {job.discovered_count}/{job.max_messages}", file=stdout)
    print(f"Pending: {job.pending_count}", file=stdout)
    print(f"Succeeded: {job.succeeded_count}", file=stdout)
    print(f"Reused: {job.reused_count}", file=stdout)
    print(f"Failed: {job.failed_count}", file=stdout)
    print(f"Interrupted: {job.interrupted_count}", file=stdout)
    print(f"Segments exhausted: {job.segments_exhausted}/12", file=stdout)
    print(
        f"Active segment: {job.active_segment if job.active_segment is not None else 'none'}",
        file=stdout,
    )


def _run_rules_check(operation_id: str, *, stdout: TextIO, stderr: TextIO) -> int:
    try:
        rules = read_triage_rules()
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    print(f"Operation: {operation_id}", file=stdout)
    if rules is None:
        print("Rules: disabled", file=stdout)
        return 0
    print("Rules: valid", file=stdout)
    print(f"Version: {rules.version}", file=stdout)
    print(f"Count: {len(rules.rules)}", file=stdout)
    return 0


def _run_history(
    operation_id: str,
    limit: int,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        settings = TriageHistorySettings.from_env()
        validate_recent_run_limit(limit)
    except (ConfigurationError, TriageRunValidationError) as error:
        return _configuration_failure(
            operation_id,
            ConfigurationError(str(error)),
            stderr=stderr,
        )
    configure_logging(settings.log_level)
    try:
        run_migrations(settings.database_path)
        with SqliteTriageRunRepository(settings.database_path) as repository:
            now = _utc_now()
            repository.recover_stale(
                stale_before=now - _stale_delta(),
                recovered_at=now,
            )
            runs = repository.recent(limit=limit)
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "runs", stderr=stderr)
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Runs: {len(runs)}", file=stdout)
    for run in runs:
        print(
            f"{run.run_id} {run.requested_at.isoformat()} {run.status.value} "
            f"documents={run.document_count} succeeded={run.succeeded_count} "
            f"reused={run.reused_count} failed={run.failed_count} "
            f"interrupted={run.interrupted_count} query={run.query_sha256[:16]}",
            file=stdout,
        )
    return 0


def _show_run(
    operation_id: str,
    run_id: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if not _valid_run_id(run_id):
        return _input_failure(
            operation_id,
            EmailValidationError("triage run ID is invalid"),
            stderr=stderr,
        )
    try:
        settings = TriageHistorySettings.from_env()
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    try:
        run_migrations(settings.database_path)
        with SqliteTriageRunRepository(settings.database_path) as repository:
            now = _utc_now()
            repository.recover_stale(
                stale_before=now - _stale_delta(),
                recovered_at=now,
            )
            details = repository.get(run_id)
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "show", stderr=stderr)
    if details is None:
        print(f"Operation: {operation_id}", file=stderr)
        print("Triage run not found", file=stderr)
        return 5
    run = details.run
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Run: {run.run_id}", file=stdout)
    print(f"Status: {run.status.value}", file=stdout)
    print(
        f"Query: {_sanitize_terminal_text(run.query_text or 'legacy query unavailable')}",
        file=stdout,
    )
    print(f"Requested: {run.requested_at.isoformat()}", file=stdout)
    for item in details.items:
        print(f"Item {item.ordinal}: {item.status.value}", file=stdout)
        print(f"  Message fingerprint: {item.message_fingerprint[:16]}", file=stdout)
        if item.received_at is not None:
            print(f"  Received: {item.received_at.isoformat()}", file=stdout)
        print(f"  Label: {item.label.value if item.label else 'unavailable'}", file=stdout)
        if item.decision_source is not None:
            print(f"  Decision source: {item.decision_source.value}", file=stdout)
        if item.rule_id is not None:
            print(f"  Rule: {item.rule_id}/{item.rule_version}", file=stdout)
        if item.failure_category is not None:
            print(f"  Failure: {item.failure_category}", file=stdout)
        if item.prompt_source is not None and item.prompt_version is not None:
            print(
                f"  Prompt: {item.prompt_source.value}/{item.prompt_version}",
                file=stdout,
            )
        if item.profile_version is not None:
            print(f"  Profile: {item.profile_version}", file=stdout)
        if item.model_alias is not None:
            print(f"  Model: {item.model_alias}", file=stdout)
        print(f"  Trace: {item.trace_id or 'unavailable'}", file=stdout)
        if item.prompt_tokens is not None:
            print(
                f"  Tokens: prompt={item.prompt_tokens} "
                f"completion={item.completion_tokens} total={item.total_tokens}",
                file=stdout,
            )
        if item.queue_wait_seconds is not None:
            print(f"  Queue wait: {item.queue_wait_seconds:.3f}s", file=stdout)
        if item.provider_seconds is not None:
            print(f"  Provider elapsed: {item.provider_seconds:.3f}s", file=stdout)
        if item.total_seconds is not None:
            print(f"  Elapsed: {item.total_seconds:.3f}s", file=stdout)
    return 0


def _run_development_reset(
    operation_id: str,
    *,
    confirmation: str,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        settings = TriageHistorySettings.from_env()
    except ConfigurationError as error:
        return _configuration_failure(operation_id, error, stderr=stderr)
    configure_logging(settings.log_level)
    if confirmation != RESET_CONFIRMATION:
        print(
            f"Operation: {operation_id}\nConfiguration error: exact reset confirmation is required",
            file=stderr,
        )
        return 2
    try:
        run_migrations(settings.database_path)
        result = reset_triage_development_data(
            settings.database_path,
            confirmation=confirmation,
            now=datetime.now(UTC),
        )
    except TriageDevelopmentResetError:
        LOGGER.warning(
            "email_triage operation_id=%s command=reset-development-data "
            "outcome=failure category=reset_refused",
            operation_id,
        )
        print(f"Operation: {operation_id}\nReset refused.", file=stderr)
        return 5
    except (OSError, sqlite3.Error):
        return _persistence_failure(operation_id, "reset-development-data", stderr=stderr)

    total = sum(result.deleted_counts.values())
    LOGGER.warning(
        "email_triage operation_id=%s command=reset-development-data "
        "outcome=success deleted_row_count=%d",
        operation_id,
        total,
    )
    print(f"Operation: {operation_id}", file=stdout)
    print(f"Backup: {result.backup_path}", file=stdout)
    print(f"Deleted email-triage rows: {total}", file=stdout)
    for table, count in result.deleted_counts.items():
        print(f"  {table}: {count}", file=stdout)
    print("Other application data: preserved", file=stdout)
    return 0


def _print_triage_result(result: MailboxTriageResult, *, stdout: TextIO) -> None:
    print(f"Operation: {result.run_id}", file=stdout)
    print(f"Run: {result.run_id}", file=stdout)
    print(f"Status: {result.status.value}", file=stdout)
    print(f"Query hash: {result.query_sha256[:16]}", file=stdout)
    print(f"Items: {len(result.items)}", file=stdout)
    print(f"Failures: {result.failure_count}", file=stdout)
    print("Gmail changes: none", file=stdout)
    for item in result.items:
        print(f"Item {item.ordinal}: {item.status.value}", file=stdout)
        print(f"  Message fingerprint: {item.message_fingerprint[:16]}", file=stdout)
        if item.received_at is not None:
            print(f"  Received: {item.received_at.isoformat()}", file=stdout)
        if item.sender is not None:
            print(f"  Sender: {_sanitize_terminal_text(item.sender)}", file=stdout)
        if item.subject is not None:
            print(f"  Subject: {_sanitize_terminal_text(item.subject)}", file=stdout)
        if item.label is not None:
            print(f"  Proposed label: {item.label.value}", file=stdout)
        if item.decision_source is not None:
            print(f"  Decision source: {item.decision_source.value}", file=stdout)
        if item.reason is not None:
            print(f"  Reason: {_sanitize_terminal_text(item.reason)}", file=stdout)
        elif item.decision_source is not None and item.decision_source.value == "rule":
            print(f"  Rule: {item.rule_id}/{item.rule_version}", file=stdout)
        elif item.status.value == "reused":
            print("  Reason: intentionally not retained", file=stdout)
        if item.failure_category is not None:
            print(f"  Failure: {item.failure_category}", file=stdout)
        if item.prompt is not None:
            print(
                f"  Prompt: {item.prompt.source.value}/{item.prompt.version}",
                file=stdout,
            )
        if item.model_alias is not None:
            print(f"  Model: {item.model_alias}", file=stdout)
        print(f"  Trace: {item.trace_id or 'unavailable'}", file=stdout)
        if item.prompt_tokens is not None:
            print(
                f"  Tokens: prompt={item.prompt_tokens} "
                f"completion={item.completion_tokens} total={item.total_tokens}",
                file=stdout,
            )
        if item.queue_wait_seconds is not None:
            print(f"  Queue wait: {item.queue_wait_seconds:.3f}s", file=stdout)
        if item.provider_seconds is not None:
            print(f"  Provider elapsed: {item.provider_seconds:.3f}s", file=stdout)
        if item.total_seconds is not None:
            print(f"  Elapsed: {item.total_seconds:.3f}s", file=stdout)
    print(f"Elapsed: {result.elapsed_seconds:.3f}s", file=stdout)


def _log_triage_result(operation_id: str, result: MailboxTriageResult) -> None:
    LOGGER.log(
        (
            logging.INFO
            if result.status is TriageRunStatus.COMPLETED_WITH_RESULTS
            else logging.WARNING
        ),
        "email_triage operation_id=%s run_id=%s command=triage outcome=%s "
        "query_sha256=%s item_count=%s failure_count=%s elapsed_seconds=%.3f",
        operation_id,
        result.run_id,
        result.status.value,
        result.query_sha256[:16],
        len(result.items),
        result.failure_count,
        result.elapsed_seconds,
    )
    for item in result.items:
        LOGGER.log(
            logging.INFO if item.status.value in {"succeeded", "reused"} else logging.WARNING,
            "email_triage operation_id=%s run_id=%s command=triage "
            "item_ordinal=%s outcome=%s category=%s decision_source=%s rule_id=%s "
            "provider=%s model=%s "
            "prompt_source=%s prompt_version=%s queue_wait_seconds=%s "
            "provider_seconds=%s total_seconds=%s prompt_tokens=%s "
            "completion_tokens=%s total_tokens=%s trace_unavailable=%s",
            operation_id,
            result.run_id,
            item.ordinal,
            item.status.value,
            item.failure_category or "none",
            item.decision_source.value if item.decision_source else "unavailable",
            item.rule_id or "unavailable",
            item.provider or "unavailable",
            item.model_alias or "unavailable",
            item.prompt.source.value if item.prompt else "unavailable",
            item.prompt.version if item.prompt else "unavailable",
            (
                f"{item.queue_wait_seconds:.3f}"
                if item.queue_wait_seconds is not None
                else "unavailable"
            ),
            (
                f"{item.provider_seconds:.3f}"
                if item.provider_seconds is not None
                else "unavailable"
            ),
            f"{item.total_seconds:.3f}" if item.total_seconds is not None else "unavailable",
            item.prompt_tokens if item.prompt_tokens is not None else "unavailable",
            (item.completion_tokens if item.completion_tokens is not None else "unavailable"),
            item.total_tokens if item.total_tokens is not None else "unavailable",
            item.trace_id is None,
        )


def _configuration_failure(
    operation_id: str,
    error: ConfigurationError,
    *,
    stderr: TextIO,
) -> int:
    print(f"Operation: {operation_id}", file=stderr)
    print(f"Configuration error: {error}", file=stderr)
    return 2


def _persistence_failure(operation_id: str, command: str, *, stderr: TextIO) -> int:
    LOGGER.warning(
        "email_triage operation_id=%s command=%s outcome=failure category=persistence",
        operation_id,
        command,
    )
    print(f"Operation: {operation_id}", file=stderr)
    print("Triage persistence failed", file=stderr)
    return 5


def _triage_protocol_failure(operation_id: str, *, stderr: TextIO) -> int:
    LOGGER.warning(
        "email_triage operation_id=%s command=triage outcome=failure category=protocol",
        operation_id,
    )
    print(f"Operation: {operation_id}", file=stderr)
    print("Triage operation failed: protocol", file=stderr)
    return 5


def _input_failure(
    operation_id: str,
    error: EmailValidationError,
    *,
    stderr: TextIO,
) -> int:
    print(f"Operation: {operation_id}", file=stderr)
    print(f"Input error: {error}", file=stderr)
    return 2


def _source_failure(
    operation_id: str,
    command: str,
    error: EmailSourceError,
    *,
    elapsed_seconds: float,
    stderr: TextIO,
    query: str | None = None,
) -> int:
    LOGGER.warning(
        "gmail_read operation_id=%s command=%s outcome=failure category=%s "
        "query_sha256=%s api_call_count=%s elapsed_seconds=%.3f http_status=%s "
        "retry_eligible=%s retry_after_seconds=%s",
        operation_id,
        command,
        error.category.value,
        _query_hash(query) if query is not None else "unavailable",
        error.api_call_count,
        elapsed_seconds,
        error.http_status,
        error.retry_eligible,
        error.retry_after_seconds,
    )
    print(f"Operation: {operation_id}", file=stderr)
    print(f"Gmail operation failed: {error.category.value}", file=stderr)
    if error.retry_after_seconds is not None:
        print(f"Retry after: {error.retry_after_seconds:g}s", file=stderr)
    return EXIT_BY_CATEGORY[error.category]


def _query_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _sanitize_terminal_text(value: str) -> str:
    return "".join(
        character if character.isprintable() or character in "\n\t" else "�" for character in value
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stale_delta() -> timedelta:
    return timedelta(seconds=300)


def _valid_run_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value))


def _valid_backfill_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", value))


if __name__ == "__main__":
    raise SystemExit(main())
