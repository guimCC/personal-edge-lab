"""Canonical Gmail-document conversion shared by triage and review."""

from __future__ import annotations

import hashlib
import json

from personal_edge_lab.domain.email import EmailDocument
from personal_edge_lab.domain.email_triage import MAX_MESSAGE_CHARS, TriageEmail
from personal_edge_lab.domain.email_triage_runs import TriageInputEvidence


def prepare_triage_input(
    document: EmailDocument,
) -> tuple[TriageInputEvidence, TriageEmail]:
    model_message = document.text[:MAX_MESSAGE_CHARS]
    email = TriageEmail(
        sender=document.sender,
        subject=document.subject,
        message=model_message,
    )
    canonical_input = json.dumps(
        {"message": email.message, "sender": email.sender, "subject": email.subject},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    cleanup_flags = tuple(
        name
        for name, enabled in (
            ("quoted_text_removed", document.quoted_text_removed),
            ("signature_removed", document.signature_removed),
            ("tracking_removed", document.tracking_removed),
            ("duplicate_lines_removed", document.duplicate_lines_removed),
        )
        if enabled
    )
    return (
        TriageInputEvidence(
            message_id=document.message_id,
            thread_id=document.thread_id,
            received_at=document.received_at,
            message_fingerprint=_sha256(document.message_id.value),
            normalized_sha256=_sha256(document.text),
            model_input_sha256=_sha256(canonical_input),
            sender_chars=len(document.sender),
            subject_chars=len(document.subject),
            normalized_chars=len(document.text),
            model_message_chars=len(model_message),
            original_size_bytes=document.original_size_bytes,
            content_source=document.content_source,
            source_truncated=document.truncated,
            model_input_truncated=len(document.text) > len(model_message),
            metadata_truncated=document.metadata_truncated,
            cleanup_flags=cleanup_flags,
        ),
        email,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
