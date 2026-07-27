"""Composition root for bounded read-only Gmail diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from personal_edge_lab.application.ports.email import (
    EmailSourceError,
    EmailSourceFailureCategory,
)
from personal_edge_lab.apps.email_triage_cli.config import (
    ConfigurationError,
    GmailAuthorizationSettings,
    GmailFetchSettings,
)
from personal_edge_lab.apps.logging_config import configure_logging
from personal_edge_lab.domain.email import EmailRetrievalRequest, EmailValidationError
from personal_edge_lab.infrastructure.gmail.client import GmailEmailSource
from personal_edge_lab.infrastructure.gmail.oauth import (
    GMAIL_READONLY_SCOPE,
    GoogleOAuthCredentialStore,
    authorize_google_oauth,
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
    return _run_fetch(
        operation_id,
        query=args.query,
        requested_limit=args.limit,
        stdout=stdout,
        stderr=stderr,
        transport=transport,
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


if __name__ == "__main__":
    raise SystemExit(main())
