from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from personal_edge_lab.apps.telegram_bot.capabilities.email_triage import (
    EmailTriageCapability,
)
from personal_edge_lab.apps.telegram_bot.contracts import (
    AuthorizedCallback,
    AuthorizedMessage,
)
from personal_edge_lab.domain.email import EmailContentSource
from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_feedback import (
    TriageFeedbackAction,
    TriageFeedbackCandidate,
    TriageFeedbackRecord,
    TriageFeedbackSource,
    TriageFeedbackSyncStatus,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.answered: list[dict[str, Any]] = []

    def send_message(self, **payload: Any) -> dict[str, Any]:
        self.sent.append(payload)
        return {"message_id": 1}

    def edit_message(self, **payload: Any) -> None:
        self.edited.append(payload)

    def answer_callback(self, **payload: Any) -> None:
        self.answered.append(payload)


def candidate() -> TriageFeedbackCandidate:
    return TriageFeedbackCandidate(
        record_id="1" * 32,
        feedback_version=0,
        recommendation_attempt_id=17,
        recommendation_label=TriageLabel.JOB,
        reason="Looks like recruiting",
        sender="<private@example.test>",
        subject="Senior role & next steps",
        received_at=NOW,
        model_input="<confidential body>",
        normalized_sha256="2" * 64,
        model_input_sha256="3" * 64,
        content_source=EmailContentSource.PLAIN_TEXT,
        cleanup_flags=(),
        source_truncated=False,
        model_input_truncated=False,
        trace_id="4" * 32,
        latest_feedback=None,
    )


def result(
    action: TriageFeedbackAction,
    corrected_label: TriageLabel | None,
) -> TriageFeedbackRecord:
    expected = (
        None if action is TriageFeedbackAction.DISMISS else corrected_label or TriageLabel.JOB
    )
    return TriageFeedbackRecord(
        feedback_id="5" * 32,
        record_id="1" * 32,
        version=1,
        recommendation_attempt_id=17,
        recommendation_label=TriageLabel.JOB,
        action=action,
        expected_label=expected,
        source=TriageFeedbackSource.TELEGRAM,
        created_at=NOW,
        sync_status=TriageFeedbackSyncStatus.SYNCED,
    )


def test_manual_queue_escapes_private_content_and_confirms_current_recommendation() -> None:
    gateway = FakeGateway()
    calls: list[tuple[object, ...]] = []

    def record_feedback(
        record_id: str,
        attempt_id: int,
        version: int,
        action: TriageFeedbackAction,
        corrected_label: TriageLabel | None,
    ) -> TriageFeedbackRecord:
        calls.append((record_id, attempt_id, version, action, corrected_label))
        return result(action, corrected_label)

    capability = EmailTriageCapability(
        gateway=gateway,
        next_candidate=candidate,
        candidate=lambda _record_id: candidate(),
        record_feedback=record_feedback,
    )
    capability.handle_command(
        "triage_review",
        AuthorizedMessage(update_id=1, chat_id=42, text="/triage_review"),
    )

    message = gateway.sent[-1]
    assert "&lt;private@example.test&gt;" in message["text"]
    assert "&lt;confidential body&gt;" in message["text"]
    buttons = message["reply_markup"]["inline_keyboard"][0]
    assert all(len(button["callback_data"].encode()) <= 64 for button in buttons)
    confirm = str(buttons[0]["callback_data"]).removeprefix("triage:")
    capability.handle_callback(
        confirm,
        AuthorizedCallback(query_id="query-1", chat_id=42, message_id=9),
    )

    assert calls == [
        (
            "1" * 32,
            17,
            0,
            TriageFeedbackAction.CONFIRM,
            None,
        )
    ]
    assert "vinculado con Langfuse" in gateway.edited[-1]["text"]
    assert "Gmail no se ha modificado" in gateway.edited[-1]["text"]


def test_correction_keyboard_records_selected_taxonomy_label() -> None:
    gateway = FakeGateway()
    calls: list[tuple[TriageFeedbackAction, TriageLabel | None]] = []
    capability = EmailTriageCapability(
        gateway=gateway,
        next_candidate=candidate,
        candidate=lambda _record_id: candidate(),
        record_feedback=lambda _record_id, _attempt, _version, action, label: (
            calls.append((action, label)) or result(action, label)
        ),
    )
    capability.handle_command(
        "triage_review",
        AuthorizedMessage(update_id=1, chat_id=42, text="/triage_review"),
    )
    correct = str(
        gateway.sent[-1]["reply_markup"]["inline_keyboard"][0][1]["callback_data"]
    ).removeprefix("triage:")
    callback = AuthorizedCallback(query_id="query-2", chat_id=42, message_id=9)
    capability.handle_callback(correct, callback)
    label_buttons = [
        button
        for row in gateway.edited[-1]["reply_markup"]["inline_keyboard"]
        for button in row
        if button["text"] == "admin"
    ]
    selected = str(label_buttons[0]["callback_data"]).removeprefix("triage:")
    capability.handle_callback(selected, callback)

    assert calls == [(TriageFeedbackAction.CORRECT, TriageLabel.ADMIN)]
