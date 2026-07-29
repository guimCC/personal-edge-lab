from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_edge_lab.domain.email import EmailContentSource
from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_feedback import (
    TriageFeedbackAction,
    TriageFeedbackCommand,
    TriageFeedbackError,
    TriageFeedbackSource,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def command(
    *,
    action: TriageFeedbackAction = TriageFeedbackAction.CONFIRM,
    corrected_label: TriageLabel | None = None,
) -> TriageFeedbackCommand:
    return TriageFeedbackCommand(
        feedback_id="1" * 32,
        record_id="2" * 32,
        recommendation_attempt_id=3,
        expected_version=0,
        action=action,
        corrected_label=corrected_label,
        source=TriageFeedbackSource.DASHBOARD,
        created_at=NOW,
    )


def test_feedback_command_enforces_action_shape() -> None:
    assert command().action is TriageFeedbackAction.CONFIRM
    assert (
        command(
            action=TriageFeedbackAction.CORRECT,
            corrected_label=TriageLabel.ADMIN,
        ).corrected_label
        is TriageLabel.ADMIN
    )

    with pytest.raises(TriageFeedbackError):
        command(action=TriageFeedbackAction.CORRECT)
    with pytest.raises(TriageFeedbackError):
        command(
            action=TriageFeedbackAction.DISMISS,
            corrected_label=TriageLabel.OTHER,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("feedback_id", "not-an-id"),
        ("record_id", "not-an-id"),
        ("recommendation_attempt_id", 0),
        ("expected_version", -1),
        ("created_at", datetime(2026, 7, 29)),
    ],
)
def test_feedback_command_rejects_invalid_identity_and_time(field, value) -> None:
    values = {
        "feedback_id": "1" * 32,
        "record_id": "2" * 32,
        "recommendation_attempt_id": 3,
        "expected_version": 0,
        "action": TriageFeedbackAction.CONFIRM,
        "corrected_label": None,
        "source": TriageFeedbackSource.TELEGRAM,
        "created_at": NOW,
    }
    values[field] = value
    with pytest.raises(TriageFeedbackError):
        TriageFeedbackCommand(**values)


def test_publication_contract_uses_normalized_source_enum() -> None:
    assert EmailContentSource.PLAIN_TEXT.value == "plain_text"
