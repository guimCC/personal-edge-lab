"""Application ports for email-triage prompts, decoding, and observations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from personal_edge_lab.domain.email_triage import (
    TriageDecision,
    TriagePrompt,
    TriageTraceRecord,
)


class TriagePromptSource(Protocol):
    def resolve(self, variables: Mapping[str, str]) -> TriagePrompt: ...


class TriageDecisionDecoder(Protocol):
    def decode(self, value: str) -> TriageDecision: ...


class TriageTraceSink(Protocol):
    def record(self, record: TriageTraceRecord) -> str | None: ...

    def close(self) -> None: ...


class NoOpTriageTraceSink:
    def record(self, record: TriageTraceRecord) -> str | None:
        del record
        return None

    def close(self) -> None:
        return None
