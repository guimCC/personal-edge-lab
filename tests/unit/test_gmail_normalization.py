from __future__ import annotations

import base64

import pytest

from personal_edge_lab.domain.email import EmailContentSource
from personal_edge_lab.infrastructure.gmail.normalization import (
    GmailMessageNormalizationError,
    decode_header_value,
    normalize_gmail_payload,
)


def _encoded(value: str, encoding: str = "utf-8") -> str:
    return base64.urlsafe_b64encode(value.encode(encoding)).decode().rstrip("=")


def _part(
    mime_type: str,
    value: str = "",
    *,
    headers: list[dict[str, str]] | None = None,
    filename: str = "",
) -> dict[str, object]:
    return {
        "mimeType": mime_type,
        "filename": filename,
        "headers": headers or [{"name": "Content-Type", "value": f"{mime_type}; charset=utf-8"}],
        "body": {"data": _encoded(value)},
    }


def test_plain_text_is_preferred_over_html_in_nested_mime() -> None:
    payload = {
        "mimeType": "multipart/mixed",
        "filename": "",
        "headers": [],
        "body": {"size": 0},
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "filename": "",
                "headers": [],
                "body": {"size": 0},
                "parts": [
                    _part("text/html", "<p>HTML version</p>"),
                    _part("text/plain", "Plain version"),
                ],
            },
            _part("application/pdf", filename="invoice.pdf"),
        ],
    }

    result = normalize_gmail_payload(payload, max_chars=8000)

    assert result.source is EmailContentSource.PLAIN_TEXT
    assert result.text == "Plain version"


def test_html_keeps_visible_text_but_removes_tracking_and_link_destinations() -> None:
    payload = _part(
        "text/html",
        "<style>.secret{}</style><p>Hello <a href='https://tracker.test/x'>owner</a></p>"
        "<span hidden>hidden text</span><span style='display: none'>also hidden</span>"
        "<img src='https://tracker.test/pixel'>",
    )

    result = normalize_gmail_payload(payload, max_chars=8000)

    assert result.source is EmailContentSource.HTML
    assert result.text == "Hello owner"
    assert result.tracking_removed
    assert "tracker" not in result.text


@pytest.mark.parametrize(
    "value",
    [
        "Hello\n\nOn Sun, Jul 27, 2026 wrote:\nold",
        "Hola\n\nEl domingo escribió:\nantiguo",
        "Hello\n--- Forwarded message ---\nold",
    ],
)
def test_standard_quoted_history_is_removed(value: str) -> None:
    result = normalize_gmail_payload(_part("text/plain", value), max_chars=8000)

    assert result.text in {"Hello", "Hola"}
    assert result.quoted_text_removed


def test_signature_duplicate_lines_and_long_text_are_bounded() -> None:
    payload = _part("text/plain", "Hello\nHello\nBody that is long\n-- \nSignature")

    result = normalize_gmail_payload(payload, max_chars=12)

    assert result.text == "Hello\nBody t"
    assert result.signature_removed
    assert result.duplicate_lines_removed
    assert result.truncated


def test_encoded_unicode_header_is_decoded() -> None:
    assert decode_header_value("=?UTF-8?B?Sm9zw6kgTcOhcnF1ZXo=?=") == "José Márquez"


def test_declared_charset_is_used() -> None:
    payload = _part(
        "text/plain",
        "factura enviada",
        headers=[{"name": "Content-Type", "value": "text/plain; charset=iso-8859-1"}],
    )
    payload["body"] = {
        "data": base64.urlsafe_b64encode("factura enviada".encode("iso-8859-1"))
        .decode()
        .rstrip("=")
    }

    assert normalize_gmail_payload(payload, max_chars=8000).text == "factura enviada"


def test_empty_inline_body_is_represented_without_inventing_content() -> None:
    result = normalize_gmail_payload(_part("text/plain"), max_chars=8000)

    assert result.source is EmailContentSource.PLAIN_TEXT
    assert result.text == ""


def test_attachment_only_message_is_unsupported() -> None:
    payload = _part("application/pdf", filename="invoice.pdf")

    with pytest.raises(GmailMessageNormalizationError) as caught:
        normalize_gmail_payload(payload, max_chars=8000)

    assert caught.value.category == "unsupported_message"


@pytest.mark.parametrize(
    "payload",
    [
        {"mimeType": "text/plain", "filename": "", "headers": [], "body": {"data": "%%%"}},
        {"mimeType": "text/plain", "filename": "", "headers": [], "body": {"data": 42}},
        {"mimeType": "multipart/mixed", "filename": "", "headers": [], "parts": "bad"},
    ],
)
def test_malformed_mime_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(GmailMessageNormalizationError) as caught:
        normalize_gmail_payload(payload, max_chars=8000)

    assert caught.value.category == "invalid_message"
