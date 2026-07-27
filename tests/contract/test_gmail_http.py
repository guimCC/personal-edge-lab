from __future__ import annotations

import base64
from collections.abc import Callable

import httpx
import pytest

from personal_edge_lab.application.ports.email import (
    EmailSourceError,
    EmailSourceFailureCategory,
)
from personal_edge_lab.domain.email import (
    EmailContentSource,
    EmailItemFailureCategory,
    EmailRetrievalRequest,
)
from personal_edge_lab.infrastructure.gmail.client import GmailEmailSource


class _Credentials:
    def __init__(self, token: str = "gmail-access-token-sentinel") -> None:
        self.token = token
        self.calls = 0

    def access_token(self) -> str:
        self.calls += 1
        return self.token


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _message(
    message_id: str,
    *,
    body: str = "Hello owner",
    mime_type: str = "text/plain",
    size: int = 1000,
    sender: str = "Sender <sender@example.test>",
    subject: str = "Subject",
) -> dict[str, object]:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "internalDate": "1785141000000",
        "sizeEstimate": size,
        "payload": {
            "mimeType": mime_type,
            "filename": "",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Content-Type", "value": f"{mime_type}; charset=utf-8"},
            ],
            "body": {"data": _encoded(body)},
        },
    }


def _source(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    credentials: _Credentials | None = None,
    max_message_bytes: int = 262_144,
) -> GmailEmailSource:
    return GmailEmailSource(
        credentials=credentials or _Credentials(),
        timeout_seconds=10,
        max_message_bytes=max_message_bytes,
        max_normalized_chars=8000,
        transport=httpx.MockTransport(handler),
    )


def test_exact_get_only_contract_and_bearer_header() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer gmail-access-token-sentinel"
        assert request.headers["Accept"] == "application/json"
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": "m1", "threadId": "thread-m1"}]},
            )
        return httpx.Response(200, json=_message("m1"))

    with _source(handler) as source:
        batch = source.retrieve(EmailRetrievalRequest(query="in:inbox newer_than:7d", limit=1))

    assert [request.method for request in requests] == ["GET", "GET"]
    assert requests[0].url.path == "/gmail/v1/users/me/messages"
    assert requests[0].url.params["q"] == "in:inbox newer_than:7d"
    assert requests[0].url.params["maxResults"] == "1"
    assert requests[0].url.params["includeSpamTrash"] == "false"
    assert requests[1].url.path == "/gmail/v1/users/me/messages/m1"
    assert requests[1].url.params["format"] == "full"
    assert batch.api_call_count == 2
    assert batch.documents[0].content_source is EmailContentSource.PLAIN_TEXT
    assert batch.documents[0].text == "Hello owner"


def test_empty_search_is_a_successful_empty_batch() -> None:
    with _source(lambda _request: httpx.Response(200, json={"resultSizeEstimate": 0})) as source:
        batch = source.retrieve(EmailRetrievalRequest(query="label:empty", limit=10))

    assert batch.documents == ()
    assert batch.failures == ()
    assert batch.api_call_count == 1


def test_pagination_is_bounded_and_continuation_is_opaque() -> None:
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal list_calls
        if request.url.path.endswith("/messages"):
            list_calls += 1
            token = request.url.params.get("pageToken")
            if list_calls == 1:
                assert token is None
                return httpx.Response(
                    200,
                    json={
                        "messages": [{"id": "m1", "threadId": "thread-m1"}],
                        "nextPageToken": "page-2",
                    },
                )
            assert token == "page-2"
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": "m2", "threadId": "thread-m2"}],
                    "nextPageToken": "page-3",
                },
            )
        return httpx.Response(200, json=_message(request.url.path.rsplit("/", 1)[-1]))

    with _source(handler) as source:
        batch = source.retrieve(EmailRetrievalRequest(query="in:inbox", limit=2))

    assert [document.message_id.value for document in batch.documents] == ["m1", "m2"]
    assert batch.pages_fetched == 2
    assert batch.next_cursor is not None
    assert batch.next_cursor.value == "page-3"


def test_pagination_never_exceeds_three_list_pages() -> None:
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal list_calls
        if request.url.path.endswith("/messages"):
            list_calls += 1
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {
                            "id": f"m{list_calls}",
                            "threadId": f"thread-m{list_calls}",
                        }
                    ],
                    "nextPageToken": f"page-{list_calls + 1}",
                },
            )
        return httpx.Response(200, json=_message(request.url.path.rsplit("/", 1)[-1]))

    with _source(handler) as source:
        batch = source.retrieve(EmailRetrievalRequest(query="in:inbox", limit=10))

    assert list_calls == 3
    assert batch.pages_fetched == 3
    assert batch.api_call_count == 6
    assert batch.next_cursor is not None
    assert batch.next_cursor.value == "page-4"


@pytest.mark.parametrize(
    ("status", "category", "retry_eligible"),
    [
        (401, EmailSourceFailureCategory.AUTHENTICATION, False),
        (403, EmailSourceFailureCategory.PERMISSION_DENIED, False),
        (429, EmailSourceFailureCategory.RATE_LIMITED, True),
        (503, EmailSourceFailureCategory.SOURCE_UNAVAILABLE, True),
        (400, EmailSourceFailureCategory.INVALID_RESPONSE, False),
    ],
)
def test_http_failures_are_sanitized_and_not_retried(
    status: int,
    category: EmailSourceFailureCategory,
    retry_eligible: bool,
) -> None:
    attempts = 0
    sentinel = "provider-body-must-never-appear"

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, text=sentinel, headers={"Retry-After": "2.5"})

    with (
        _source(handler) as source,
        pytest.raises(EmailSourceError) as caught,
    ):
        source.retrieve(EmailRetrievalRequest(query="in:inbox"))

    assert attempts == 1
    assert caught.value.category is category
    assert caught.value.retry_eligible is retry_eligible
    assert caught.value.retry_after_seconds == 2.5
    assert sentinel not in str(caught.value)


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (httpx.ConnectError("secret connection detail"), EmailSourceFailureCategory.CONNECTION),
        (httpx.ReadTimeout("secret timeout detail"), EmailSourceFailureCategory.TIMEOUT),
    ],
)
def test_transport_failures_are_sanitized(
    exception: httpx.RequestError,
    category: EmailSourceFailureCategory,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise exception

    with (
        _source(handler) as source,
        pytest.raises(EmailSourceError) as caught,
    ):
        source.retrieve(EmailRetrievalRequest(query="in:inbox"))

    assert caught.value.category is category
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"messages":"invalid"}'])
def test_malformed_list_response_is_invalid(body: bytes) -> None:
    with (
        _source(lambda _request: httpx.Response(200, content=body)) as source,
        pytest.raises(EmailSourceError) as caught,
    ):
        source.retrieve(EmailRetrievalRequest(query="in:inbox"))

    assert caught.value.category is EmailSourceFailureCategory.INVALID_RESPONSE


def test_oversized_or_unsupported_messages_are_partial_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {"id": "large", "threadId": "thread-large"},
                        {"id": "attachment", "threadId": "thread-attachment"},
                    ]
                },
            )
        if request.url.path.endswith("/large"):
            return httpx.Response(200, json=_message("large", size=101))
        value = _message("attachment", mime_type="application/pdf", size=100)
        value["payload"]["filename"] = "invoice.pdf"  # type: ignore[index]
        return httpx.Response(200, json=value)

    with _source(handler, max_message_bytes=100) as source:
        batch = source.retrieve(EmailRetrievalRequest(query="in:inbox", limit=2))

    assert batch.documents == ()
    assert [failure.category for failure in batch.failures] == [
        EmailItemFailureCategory.MESSAGE_TOO_LARGE,
        EmailItemFailureCategory.UNSUPPORTED_MESSAGE,
    ]


def test_success_response_size_is_bounded() -> None:
    body = b'{"messages":[],"padding":"' + b"x" * 70_000 + b'"}'
    with (
        _source(
            lambda _request: httpx.Response(200, content=body),
            max_message_bytes=1,
        ) as source,
        pytest.raises(EmailSourceError) as caught,
    ):
        source.retrieve(EmailRetrievalRequest(query="in:inbox"))

    assert caught.value.category is EmailSourceFailureCategory.INVALID_RESPONSE


def test_close_is_idempotent_and_closed_source_cannot_be_reused() -> None:
    source = _source(lambda _request: httpx.Response(200, json={}))

    source.close()
    source.close()

    with pytest.raises(RuntimeError, match="closed"):
        source.retrieve(EmailRetrievalRequest(query="in:inbox"))
