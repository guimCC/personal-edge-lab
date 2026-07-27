from __future__ import annotations

import pytest

from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    TriageDecision,
    TriageEmail,
    TriageLabel,
    TriageProfile,
    TriagePromptIdentity,
    TriageValidationError,
)


@pytest.mark.parametrize("label", list(TriageLabel))
def test_all_provisional_labels_are_valid(label: TriageLabel) -> None:
    decision = TriageDecision(label=label, reason="Bounded reason")
    assert decision.label is label
    assert set(TriageDecision.__dataclass_fields__) == {"label", "reason"}


@pytest.mark.parametrize(
    "values",
    [
        {"sender": "", "subject": "subject", "message": ""},
        {"sender": "x" * 161, "subject": "subject", "message": ""},
        {"sender": "sender@example.test", "subject": "x" * 257, "message": ""},
        {"sender": "sender@example.test", "subject": "", "message": "x" * 1601},
        {"sender": "sender@example.test", "subject": " ", "message": "\n"},
    ],
)
def test_invalid_email_bounds_are_rejected(values: dict[str, str]) -> None:
    with pytest.raises(TriageValidationError):
        TriageEmail(**values)


def test_subject_or_message_can_individually_be_empty() -> None:
    assert TriageEmail("sender@example.test", "Subject", "").subject == "Subject"
    assert TriageEmail("sender@example.test", "", "Body").message == "Body"


@pytest.mark.parametrize("reason", ["", " ", "x" * 161])
def test_invalid_reason_is_rejected(reason: str) -> None:
    with pytest.raises(TriageValidationError):
        TriageDecision(label=TriageLabel.OTHER, reason=reason)


def test_profile_and_prompt_identity_are_explicitly_versioned() -> None:
    profile = TriageProfile(
        name="email-triage",
        version="1.0.0",
        taxonomy_version="1.0.0",
        schema_version="1.0.0",
        generation_parameters_version="1.0.0",
    )
    prompt = TriagePromptIdentity(
        name="personal-edge-lab/email-triage",
        version="7",
        source=PromptSourceKind.LANGFUSE,
    )
    assert profile.max_output_tokens == 64
    assert profile.temperature == 0
    assert prompt.version == "7"
