"""Gmail MIME and HTML normalization confined to the Gmail adapter."""

from __future__ import annotations

import base64
import binascii
import codecs
import re
import unicodedata
from dataclasses import dataclass
from email.header import decode_header
from html.parser import HTMLParser
from typing import Any

from personal_edge_lab.domain.email import EmailContentSource

_CHARSET_PATTERN = re.compile(r"charset\s*=\s*[\"']?([^;\"'\s]+)", re.IGNORECASE)
_QUOTE_PATTERNS = (
    re.compile(r"^On .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^El .+ escribió:\s*$", re.IGNORECASE),
    re.compile(
        r"^-{2,}\s*(?:Original Message|Mensaje original|Forwarded message|Mensaje reenviado)"
        r"\s*-{2,}$",
        re.IGNORECASE,
    ),
)
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
}
_IGNORED_TAGS = {"head", "script", "style", "svg", "template"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}


class GmailMessageNormalizationError(ValueError):
    """Internal marker for malformed or unsupported Gmail message content."""

    def __init__(self, category: str) -> None:
        super().__init__("Gmail message content could not be normalized")
        self.category = category


@dataclass(frozen=True, slots=True)
class NormalizedEmailContent:
    text: str
    source: EmailContentSource
    truncated: bool
    quoted_text_removed: bool
    signature_removed: bool
    tracking_removed: bool
    duplicate_lines_removed: bool


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0
        self.tag_stack: list[tuple[str, bool]] = []
        self.tracking_removed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        hidden = lowered in _IGNORED_TAGS or _attributes_hide_content(attrs)
        if lowered not in _VOID_TAGS:
            self.tag_stack.append((lowered, hidden))
        if hidden:
            if lowered not in _VOID_TAGS:
                self.ignored_depth += 1
            self.tracking_removed = True
            return
        if self.ignored_depth:
            return
        if lowered in {"img", "link", "meta"}:
            self.tracking_removed = True
            return
        if lowered == "a" and any(name.lower() == "href" and value for name, value in attrs):
            self.tracking_removed = True
        if lowered in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in _VOID_TAGS:
            return
        was_ignored = self.ignored_depth > 0
        matching_index = next(
            (
                index
                for index in range(len(self.tag_stack) - 1, -1, -1)
                if self.tag_stack[index][0] == lowered
            ),
            None,
        )
        if matching_index is not None:
            closed = self.tag_stack[matching_index:]
            self.tag_stack = self.tag_stack[:matching_index]
            self.ignored_depth -= sum(1 for _tag, hidden in closed if hidden)
        if not was_ignored and not self.ignored_depth and lowered in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _attributes_hide_content(attrs: list[tuple[str, str | None]]) -> bool:
    normalized = {name.lower(): (value or "").lower() for name, value in attrs}
    style = normalized.get("style", "").replace(" ", "")
    return (
        "hidden" in normalized
        or normalized.get("aria-hidden") == "true"
        or "display:none" in style
        or "visibility:hidden" in style
    )


def decode_header_value(value: object) -> str:
    if not isinstance(value, str):
        raise GmailMessageNormalizationError("invalid_message")
    pieces: list[str] = []
    try:
        decoded = decode_header(value)
    except (LookupError, ValueError) as error:
        raise GmailMessageNormalizationError("invalid_message") from error
    for part, charset in decoded:
        if isinstance(part, str):
            pieces.append(part)
            continue
        encoding = charset or "utf-8"
        try:
            pieces.append(part.decode(encoding, errors="strict"))
        except (LookupError, UnicodeDecodeError) as error:
            raise GmailMessageNormalizationError("invalid_message") from error
    return unicodedata.normalize("NFC", "".join(pieces)).strip()


def normalize_gmail_payload(payload: object, *, max_chars: int) -> NormalizedEmailContent:
    if not isinstance(payload, dict):
        raise GmailMessageNormalizationError("invalid_message")
    plain_parts: list[str] = []
    html_parts: list[str] = []
    state = {"attachment_seen": False}
    _collect_text_parts(payload, plain_parts, html_parts, state)
    tracking_removed = False
    if plain_parts:
        source = EmailContentSource.PLAIN_TEXT
        selected = "\n\n".join(plain_parts)
    elif html_parts:
        source = EmailContentSource.HTML
        rendered: list[str] = []
        for part in html_parts:
            parser = _VisibleTextParser()
            try:
                parser.feed(part)
                parser.close()
            except Exception as error:
                raise GmailMessageNormalizationError("invalid_message") from error
            rendered.append("".join(parser.parts))
            tracking_removed = tracking_removed or parser.tracking_removed
        selected = "\n\n".join(rendered)
    elif state["attachment_seen"]:
        raise GmailMessageNormalizationError("unsupported_message")
    else:
        source = EmailContentSource.EMPTY
        selected = ""

    text, quoted_removed, signature_removed, duplicates_removed = _clean_text(selected)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rstrip()
    return NormalizedEmailContent(
        text=text,
        source=source,
        truncated=truncated,
        quoted_text_removed=quoted_removed,
        signature_removed=signature_removed,
        tracking_removed=tracking_removed,
        duplicate_lines_removed=duplicates_removed,
    )


def _collect_text_parts(
    part: dict[str, Any],
    plain_parts: list[str],
    html_parts: list[str],
    state: dict[str, bool],
) -> None:
    mime_type = part.get("mimeType")
    if not isinstance(mime_type, str):
        raise GmailMessageNormalizationError("invalid_message")
    filename = part.get("filename", "")
    if not isinstance(filename, str):
        raise GmailMessageNormalizationError("invalid_message")
    headers = _headers(part.get("headers", []))
    disposition = headers.get("content-disposition", "")
    is_attachment = bool(filename.strip()) or disposition.lower().startswith("attachment")
    if is_attachment:
        state["attachment_seen"] = True
        return

    child_parts = part.get("parts")
    if child_parts is not None:
        if not isinstance(child_parts, list):
            raise GmailMessageNormalizationError("invalid_message")
        for child in child_parts:
            if not isinstance(child, dict):
                raise GmailMessageNormalizationError("invalid_message")
            _collect_text_parts(child, plain_parts, html_parts, state)

    lowered = mime_type.lower()
    if lowered not in {"text/plain", "text/html"}:
        return
    body = part.get("body")
    if not isinstance(body, dict):
        raise GmailMessageNormalizationError("invalid_message")
    attachment_id = body.get("attachmentId")
    data = body.get("data")
    if attachment_id is not None and not data:
        state["attachment_seen"] = True
        return
    if data is None:
        data = ""
    if not isinstance(data, str):
        raise GmailMessageNormalizationError("invalid_message")
    decoded = _decode_body(data, headers.get("content-type", ""))
    if lowered == "text/plain":
        plain_parts.append(decoded)
    else:
        html_parts.append(decoded)


def _headers(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        raise GmailMessageNormalizationError("invalid_message")
    headers: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            raise GmailMessageNormalizationError("invalid_message")
        name = item.get("name")
        header_value = item.get("value")
        if not isinstance(name, str) or not isinstance(header_value, str):
            raise GmailMessageNormalizationError("invalid_message")
        headers.setdefault(name.lower(), header_value)
    return headers


def _decode_body(value: str, content_type: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as error:
        raise GmailMessageNormalizationError("invalid_message") from error
    charset_match = _CHARSET_PATTERN.search(content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        codecs.lookup(charset)
        decoded = raw.decode(charset, errors="strict")
    except (LookupError, UnicodeDecodeError) as error:
        raise GmailMessageNormalizationError("invalid_message") from error
    return unicodedata.normalize("NFC", decoded)


def _clean_text(value: str) -> tuple[str, bool, bool, bool]:
    value = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in value.split("\n")]
    quoted_removed = False
    signature_removed = False
    cut_at = len(lines)
    for index, line in enumerate(lines):
        if any(pattern.match(line) for pattern in _QUOTE_PATTERNS):
            cut_at = index
            quoted_removed = True
            break
        if line == "--":
            cut_at = index
            signature_removed = True
            break
    lines = lines[:cut_at]

    deduplicated: list[str] = []
    duplicates_removed = False
    for line in lines:
        if line and deduplicated and line == deduplicated[-1]:
            duplicates_removed = True
            continue
        deduplicated.append(line)

    compact: list[str] = []
    previous_blank = True
    for line in deduplicated:
        if not line:
            if not previous_blank:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False
    while compact and not compact[-1]:
        compact.pop()
    return "\n".join(compact), quoted_removed, signature_removed, duplicates_removed
