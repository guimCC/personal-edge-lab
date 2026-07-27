"""Pure contracts for bounded email classification."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from personal_edge_lab.domain.ai import (
    CompletionRequest,
    CompletionResult,
    CompletionTiming,
    ModelMessage,
    ModelRole,
    TokenUsage,
)

MAX_SENDER_CHARS = 160
MAX_SUBJECT_CHARS = 256
MAX_MESSAGE_CHARS = 1600
MAX_REASON_CHARS = 160
MAX_PROMPT_VERSION_CHARS = 64
VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class TriageValidationError(ValueError):
    """Raised when email-triage data violates the bounded contract."""


class TriageOutputError(RuntimeError):
    """Raised when model output is not an exact triage decision."""


class TriageLabel(StrEnum):
    WORK = "work"
    BILLING = "billing"
    NOTIFICATION = "notification"
    NEWSLETTER = "newsletter"
    PERSONAL = "personal"
    OTHER = "other"


class PromptSourceKind(StrEnum):
    LANGFUSE = "langfuse"
    LOCAL_FALLBACK = "local_fallback"


class TriageTraceContentKind(StrEnum):
    SYNTHETIC_FULL = "synthetic_full"
    GMAIL_REDACTED = "gmail_redacted"


@dataclass(frozen=True, slots=True)
class TriageEmail:
    sender: str
    subject: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.sender, str) or not self.sender.strip():
            raise TriageValidationError("sender must not be blank")
        if len(self.sender) > MAX_SENDER_CHARS:
            raise TriageValidationError(f"sender must not exceed {MAX_SENDER_CHARS} characters")
        if not isinstance(self.subject, str) or len(self.subject) > MAX_SUBJECT_CHARS:
            raise TriageValidationError(f"subject must not exceed {MAX_SUBJECT_CHARS} characters")
        if not isinstance(self.message, str) or len(self.message) > MAX_MESSAGE_CHARS:
            raise TriageValidationError(f"message must not exceed {MAX_MESSAGE_CHARS} characters")
        if not self.subject.strip() and not self.message.strip():
            raise TriageValidationError("subject or message must not be blank")


@dataclass(frozen=True, slots=True)
class TriageDecision:
    label: TriageLabel
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.label, TriageLabel):
            raise TriageValidationError("triage label is invalid")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise TriageValidationError("triage reason must not be blank")
        if len(self.reason) > MAX_REASON_CHARS:
            raise TriageValidationError(
                f"triage reason must not exceed {MAX_REASON_CHARS} characters"
            )


@dataclass(frozen=True, slots=True)
class TriageProfile:
    name: str
    version: str
    taxonomy_version: str
    schema_version: str
    generation_parameters_version: str
    max_output_tokens: int = 64
    temperature: float = 0

    def __post_init__(self) -> None:
        versioned = (
            self.name,
            self.version,
            self.taxonomy_version,
            self.schema_version,
            self.generation_parameters_version,
        )
        if any(
            not isinstance(value, str)
            or len(value) > MAX_PROMPT_VERSION_CHARS
            or VERSION_PATTERN.fullmatch(value) is None
            for value in versioned
        ):
            raise TriageValidationError("triage profile identity is invalid")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 1 <= self.max_output_tokens <= 256
        ):
            raise TriageValidationError("triage output-token limit is invalid")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(float(self.temperature))
            or float(self.temperature) != 0
        ):
            raise TriageValidationError("triage temperature must be zero")


@dataclass(frozen=True, slots=True)
class TriagePromptIdentity:
    name: str
    version: str
    source: PromptSourceKind

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 160:
            raise TriageValidationError("prompt name is invalid")
        if not isinstance(self.version, str) or not self.version.strip() or len(self.version) > 64:
            raise TriageValidationError("prompt version is invalid")
        if not isinstance(self.source, PromptSourceKind):
            raise TriageValidationError("prompt source is invalid")


@dataclass(frozen=True, slots=True)
class TriagePrompt:
    identity: TriagePromptIdentity
    messages: tuple[ModelMessage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, TriagePromptIdentity):
            raise TriageValidationError("prompt identity is invalid")
        if not isinstance(self.messages, tuple) or not self.messages:
            raise TriageValidationError("prompt messages must not be empty")
        if not all(isinstance(message, ModelMessage) for message in self.messages):
            raise TriageValidationError("prompt messages are invalid")


@dataclass(frozen=True, slots=True)
class TriagePromptManifest:
    name: str
    version: str
    messages: tuple[tuple[ModelRole, str], ...]


@dataclass(frozen=True, slots=True)
class PreparedTriage:
    email: TriageEmail
    prompt: TriagePrompt
    profile: TriageProfile
    request: CompletionRequest


@dataclass(frozen=True, slots=True)
class SyntheticTriageTracePayload:
    email: TriageEmail
    prompt_messages: tuple[ModelMessage, ...]
    raw_output: str | None
    decision: TriageDecision | None


@dataclass(frozen=True, slots=True)
class RedactedTriageTracePayload:
    content_sha256: str
    decision_sha256: str | None
    sender_chars: int
    subject_chars: int
    message_chars: int
    source: str
    cleanup_flags: tuple[str, ...]
    label: TriageLabel | None = None
    reason_chars: int | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise TriageValidationError("redacted content hash is invalid")
        if (
            self.decision_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.decision_sha256) is None
        ):
            raise TriageValidationError("redacted decision hash is invalid")
        counts = (self.sender_chars, self.subject_chars, self.message_chars)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
        ):
            raise TriageValidationError("redacted content lengths are invalid")
        if not isinstance(self.source, str) or not self.source:
            raise TriageValidationError("redacted source is invalid")
        if not isinstance(self.cleanup_flags, tuple) or not all(
            isinstance(value, str) and value for value in self.cleanup_flags
        ):
            raise TriageValidationError("redacted cleanup flags are invalid")
        if self.label is not None and not isinstance(self.label, TriageLabel):
            raise TriageValidationError("redacted label is invalid")
        if self.reason_chars is not None and (
            isinstance(self.reason_chars, bool)
            or not isinstance(self.reason_chars, int)
            or not 0 <= self.reason_chars <= MAX_REASON_CHARS
        ):
            raise TriageValidationError("redacted reason length is invalid")


@dataclass(frozen=True, slots=True)
class TriageTraceRecord:
    trace_id: str
    operation_id: str
    prompt: TriagePromptIdentity
    profile: TriageProfile
    provider: str
    model_alias: str
    usage: TokenUsage | None
    timing: CompletionTiming | None
    payload: SyntheticTriageTracePayload | RedactedTriageTracePayload
    outcome: str
    failure_category: str | None = None
    failure_queue_wait_seconds: float = 0
    failure_provider_seconds: float | None = None
    attempt_count: int = 1
    retry_eligible: bool | None = None
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class TriageEvidence:
    operation_id: str
    trace_id: str | None
    trace_unavailable: bool
    prompt: TriagePromptIdentity
    profile: TriageProfile
    completion: CompletionResult


@dataclass(frozen=True, slots=True)
class TriageResult:
    decision: TriageDecision
    evidence: TriageEvidence
