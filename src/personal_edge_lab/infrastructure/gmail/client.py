"""Bounded GET-only Gmail adapter implementing the email-source port."""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from personal_edge_lab.application.ports.email import (
    EmailSourceError,
    EmailSourceFailureCategory,
)
from personal_edge_lab.domain.email import (
    MAX_EMAIL_PAGES,
    MAX_EMAIL_SENDER_CHARS,
    MAX_EMAIL_SUBJECT_CHARS,
    EmailDocument,
    EmailItemFailure,
    EmailItemFailureCategory,
    EmailMessageId,
    EmailRetrievalBatch,
    EmailRetrievalCursor,
    EmailRetrievalRequest,
    EmailThreadId,
)
from personal_edge_lab.infrastructure.gmail.normalization import (
    GmailMessageNormalizationError,
    decode_header_value,
    normalize_gmail_payload,
)

GMAIL_API_ORIGIN = "https://gmail.googleapis.com"


class GmailCredentialProvider(Protocol):
    def access_token(self) -> str: ...


class GmailEmailSource:
    """Retrieve a bounded Gmail batch using list and full-message GETs only."""

    def __init__(
        self,
        *,
        credentials: GmailCredentialProvider,
        timeout_seconds: float,
        max_message_bytes: int,
        max_normalized_chars: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credentials = credentials
        self._max_message_bytes = max_message_bytes
        self._max_normalized_chars = max_normalized_chars
        self._max_response_bytes = max(65_536, max_message_bytes * 6)
        self._client = httpx.Client(
            base_url=GMAIL_API_ORIGIN,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )
        self._closed = False
        self._api_call_count = 0

    def __enter__(self) -> GmailEmailSource:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._client.close()
            self._closed = True

    def retrieve(self, request: EmailRetrievalRequest) -> EmailRetrievalBatch:
        if self._closed:
            raise RuntimeError("Gmail email source is closed")
        started = time.perf_counter()
        self._api_call_count = 0
        access_token = self._credentials.access_token()
        message_ids, next_cursor, pages_fetched = self._list_message_ids(
            request,
            access_token=access_token,
        )
        documents: list[EmailDocument] = []
        failures: list[EmailItemFailure] = []
        for message_id in message_ids:
            response = self._get_json(
                f"/gmail/v1/users/me/messages/{quote(message_id.value, safe='')}",
                params={"format": "full"},
                access_token=access_token,
            )
            try:
                documents.append(self._parse_message(response, expected_id=message_id))
            except GmailMessageNormalizationError as error:
                failures.append(
                    EmailItemFailure(
                        _item_failure_category(error.category),
                        message_id=message_id,
                    )
                )
        return EmailRetrievalBatch(
            documents=tuple(documents),
            failures=tuple(failures),
            next_cursor=next_cursor,
            pages_fetched=pages_fetched,
            api_call_count=self._api_call_count,
            elapsed_seconds=time.perf_counter() - started,
        )

    def _list_message_ids(
        self,
        request: EmailRetrievalRequest,
        *,
        access_token: str,
    ) -> tuple[list[EmailMessageId], EmailRetrievalCursor | None, int]:
        message_ids: list[EmailMessageId] = []
        next_page_token = request.cursor.value if request.cursor is not None else None
        pages_fetched = 0
        while len(message_ids) < request.limit and pages_fetched < MAX_EMAIL_PAGES:
            params: dict[str, str | int] = {
                "q": request.query,
                "maxResults": request.limit - len(message_ids),
                "includeSpamTrash": "false",
            }
            if next_page_token is not None:
                params["pageToken"] = next_page_token
            response = self._get_json(
                "/gmail/v1/users/me/messages",
                params=params,
                access_token=access_token,
            )
            pages_fetched += 1
            raw_messages = response.get("messages", [])
            if not isinstance(raw_messages, list):
                raise self._invalid_response()
            for item in raw_messages:
                if not isinstance(item, dict):
                    raise self._invalid_response()
                raw_id = item.get("id")
                raw_thread_id = item.get("threadId")
                if not isinstance(raw_id, str) or not isinstance(raw_thread_id, str):
                    raise self._invalid_response()
                try:
                    message_id = EmailMessageId(raw_id)
                    EmailThreadId(raw_thread_id)
                except (TypeError, ValueError) as error:
                    raise self._invalid_response() from error
                if message_id not in message_ids:
                    message_ids.append(message_id)
                if len(message_ids) >= request.limit:
                    break
            raw_next_page = response.get("nextPageToken")
            if raw_next_page is None:
                next_page_token = None
                break
            try:
                next_page_token = EmailRetrievalCursor(raw_next_page).value
            except (TypeError, ValueError) as error:
                raise self._invalid_response() from error
            if not raw_messages:
                break
        cursor = EmailRetrievalCursor(next_page_token) if next_page_token is not None else None
        return message_ids, cursor, pages_fetched

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str | int],
        access_token: str,
    ) -> dict[str, Any]:
        self._api_call_count += 1
        try:
            with self._client.stream(
                "GET",
                path,
                params=params,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            ) as response:
                if response.status_code != 200:
                    raise self._http_error(response)
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self._max_response_bytes:
                        raise self._invalid_response()
                    chunks.append(chunk)
        except httpx.TimeoutException as error:
            raise EmailSourceError(
                "Gmail request timed out",
                category=EmailSourceFailureCategory.TIMEOUT,
                retry_eligible=True,
                api_call_count=self._api_call_count,
            ) from error
        except httpx.RequestError as error:
            raise EmailSourceError(
                "Gmail connection failed",
                category=EmailSourceFailureCategory.CONNECTION,
                retry_eligible=True,
                api_call_count=self._api_call_count,
            ) from error
        try:
            value = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise self._invalid_response() from error
        if not isinstance(value, dict):
            raise self._invalid_response()
        return value

    def _parse_message(
        self,
        value: dict[str, Any],
        *,
        expected_id: EmailMessageId,
    ) -> EmailDocument:
        raw_message_id = value.get("id")
        raw_thread_id = value.get("threadId")
        if not isinstance(raw_message_id, str) or not isinstance(raw_thread_id, str):
            raise GmailMessageNormalizationError("invalid_message")
        try:
            message_id = EmailMessageId(raw_message_id)
            thread_id = EmailThreadId(raw_thread_id)
        except (TypeError, ValueError) as error:
            raise GmailMessageNormalizationError("invalid_message") from error
        if message_id != expected_id:
            raise GmailMessageNormalizationError("invalid_message")
        raw_size = value.get("sizeEstimate")
        if isinstance(raw_size, bool) or not isinstance(raw_size, int) or raw_size < 0:
            raise GmailMessageNormalizationError("invalid_message")
        if raw_size > self._max_message_bytes:
            raise GmailMessageNormalizationError("message_too_large")
        raw_internal_date = value.get("internalDate")
        if not isinstance(raw_internal_date, str) or not raw_internal_date.isdecimal():
            raise GmailMessageNormalizationError("invalid_message")
        try:
            timestamp = int(raw_internal_date) / 1000
            if not math.isfinite(timestamp):
                raise ValueError
            received_at = datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError) as error:
            raise GmailMessageNormalizationError("invalid_message") from error

        payload = value.get("payload")
        if not isinstance(payload, dict):
            raise GmailMessageNormalizationError("invalid_message")
        headers = _message_headers(payload.get("headers"))
        sender = decode_header_value(headers.get("from", ""))
        subject = decode_header_value(headers.get("subject", ""))
        if not sender:
            raise GmailMessageNormalizationError("invalid_message")
        metadata_truncated = (
            len(sender) > MAX_EMAIL_SENDER_CHARS or len(subject) > MAX_EMAIL_SUBJECT_CHARS
        )
        sender = sender[:MAX_EMAIL_SENDER_CHARS]
        subject = subject[:MAX_EMAIL_SUBJECT_CHARS]
        content = normalize_gmail_payload(payload, max_chars=self._max_normalized_chars)
        try:
            return EmailDocument(
                message_id=message_id,
                thread_id=thread_id,
                received_at=received_at,
                sender=sender,
                subject=subject,
                text=content.text,
                content_source=content.source,
                original_size_bytes=raw_size,
                normalized_char_count=len(content.text),
                truncated=content.truncated,
                metadata_truncated=metadata_truncated,
                quoted_text_removed=content.quoted_text_removed,
                signature_removed=content.signature_removed,
                tracking_removed=content.tracking_removed,
                duplicate_lines_removed=content.duplicate_lines_removed,
            )
        except ValueError as error:
            raise GmailMessageNormalizationError("invalid_message") from error

    def _http_error(self, response: httpx.Response) -> EmailSourceError:
        status = response.status_code
        retry_after = _numeric_retry_after(response.headers.get("Retry-After"))
        if status == 401:
            category = EmailSourceFailureCategory.AUTHENTICATION
            retry_eligible = False
            message = "Gmail authentication failed; authorize the integration again"
        elif status == 403:
            category = EmailSourceFailureCategory.PERMISSION_DENIED
            retry_eligible = False
            message = "Gmail read permission was denied"
        elif status == 429:
            category = EmailSourceFailureCategory.RATE_LIMITED
            retry_eligible = True
            message = "Gmail rate limit was reached"
        elif 500 <= status <= 599:
            category = EmailSourceFailureCategory.SOURCE_UNAVAILABLE
            retry_eligible = True
            message = "Gmail is unavailable"
        else:
            category = EmailSourceFailureCategory.INVALID_RESPONSE
            retry_eligible = False
            message = "Gmail rejected the read-only request"
        return EmailSourceError(
            message,
            category=category,
            retry_eligible=retry_eligible,
            http_status=status,
            retry_after_seconds=retry_after,
            api_call_count=self._api_call_count,
        )

    def _invalid_response(self) -> EmailSourceError:
        return EmailSourceError(
            "Gmail returned an invalid response",
            category=EmailSourceFailureCategory.INVALID_RESPONSE,
            retry_eligible=False,
            api_call_count=self._api_call_count,
        )


def _message_headers(value: object) -> dict[str, object]:
    if not isinstance(value, list):
        raise GmailMessageNormalizationError("invalid_message")
    headers: dict[str, object] = {}
    for item in value:
        if not isinstance(item, dict):
            raise GmailMessageNormalizationError("invalid_message")
        name = item.get("name")
        header_value = item.get("value")
        if not isinstance(name, str) or not isinstance(header_value, str):
            raise GmailMessageNormalizationError("invalid_message")
        headers.setdefault(name.lower(), header_value)
    return headers


def _numeric_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _item_failure_category(value: str) -> EmailItemFailureCategory:
    try:
        return EmailItemFailureCategory(value)
    except ValueError:
        return EmailItemFailureCategory.INVALID_MESSAGE
