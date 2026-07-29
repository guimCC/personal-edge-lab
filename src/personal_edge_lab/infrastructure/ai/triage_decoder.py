"""Strict Pydantic parsing boundary for email-triage output."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from personal_edge_lab.domain.email_triage import (
    TriageDecision,
    TriageLabel,
    TriageOutputError,
)


class _TriageDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: TriageLabel
    reason: str = Field(min_length=1, max_length=160, pattern=r".*\S.*")

    @field_validator("label")
    @classmethod
    def current_taxonomy_only(cls, value: TriageLabel) -> TriageLabel:
        if value.is_legacy:
            raise ValueError("legacy labels are not valid model output")
        return value


class PydanticTriageDecisionDecoder:
    def decode(self, value: str) -> TriageDecision:
        if not isinstance(value, str) or not value:
            raise TriageOutputError("model returned invalid triage output")
        try:
            payload = _TriageDecisionPayload.model_validate_json(value)
        except (ValidationError, ValueError) as error:
            raise TriageOutputError("model returned invalid triage output") from error
        return TriageDecision(label=payload.label, reason=payload.reason)
