from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_edge_lab.domain.email import EmailContentSource
from personal_edge_lab.domain.email_triage_messages import (
    TriageContentSnapshot,
    TriageMessageCursor,
    TriageMessageValidationError,
    validate_message_limit,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def snapshot(**overrides) -> TriageContentSnapshot:
    values = {
        "sender": "Sender <sender@example.test>",
        "subject": "Subject",
        "normalized_text": "message text",
        "model_input": "message text",
        "normalized_sha256": "a" * 64,
        "model_input_sha256": "b" * 64,
        "original_size_bytes": 12,
        "content_source": EmailContentSource.PLAIN_TEXT,
        "cleanup_flags": ("quoted_text_removed",),
        "source_truncated": False,
        "model_input_truncated": False,
        "metadata_truncated": False,
    }
    values.update(overrides)
    return TriageContentSnapshot(**values)


def test_content_snapshot_accepts_bounded_exact_model_prefix() -> None:
    value = snapshot(normalized_text="model input and remainder", model_input="model input")
    assert value.model_input == "model input"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sender": ""},
        {"subject": "s" * 257},
        {"normalized_text": "x" * 8001},
        {"model_input": "not a prefix"},
        {"normalized_sha256": "not-a-hash"},
    ],
)
def test_content_snapshot_rejects_invalid_product_data(overrides) -> None:
    with pytest.raises(TriageMessageValidationError):
        snapshot(**overrides)


def test_cursor_and_limit_are_strictly_bounded() -> None:
    assert validate_message_limit(100) == 100
    assert TriageMessageCursor(NOW, "a" * 32).record_id == "a" * 32
    with pytest.raises(TriageMessageValidationError):
        validate_message_limit(101)
    with pytest.raises(TriageMessageValidationError):
        TriageMessageCursor(NOW.replace(tzinfo=None), "a" * 32)
