"""Environment configuration for bounded read-only Gmail diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from personal_edge_lab.apps.ai_cli.config import CompletionSettings, LangfuseSettings
from personal_edge_lab.apps.configuration import (
    ConfigurationError as ConfigurationError,
)
from personal_edge_lab.apps.configuration import (
    read_bool,
    read_file_path,
    read_log_level,
    read_positive_int,
)
from personal_edge_lab.apps.gmail_configuration import (
    GmailAuthorizationSettings as GmailAuthorizationSettings,
)
from personal_edge_lab.apps.gmail_configuration import (
    GmailFetchSettings,
    read_private_json,
)
from personal_edge_lab.domain.email_triage import TriageRuleSet, TriageValidationError
from personal_edge_lab.modules.email_triage.rules import parse_rule_set


@dataclass(frozen=True, slots=True)
class MailboxTriageSettings:
    gmail: GmailFetchSettings
    completion: CompletionSettings
    langfuse: LangfuseSettings
    database_path: Path
    log_level: int
    rules: TriageRuleSet | None = None

    @classmethod
    def from_env(cls) -> MailboxTriageSettings:
        if not read_bool("GMAIL_TRIAGE_ENABLED", "false"):
            raise ConfigurationError("GMAIL_TRIAGE_ENABLED must be true for triage")
        gmail = GmailFetchSettings.from_env()
        completion = CompletionSettings.from_env()
        langfuse = LangfuseSettings.from_env()
        database_path = read_file_path("DATABASE_PATH", "./data/telemetry.db")
        level, _level_name = read_log_level()
        rules = read_triage_rules()
        return cls(
            gmail=gmail,
            completion=completion,
            langfuse=langfuse,
            database_path=database_path,
            log_level=level,
            rules=rules,
        )


def read_triage_rules() -> TriageRuleSet | None:
    raw_path = os.environ.get("EMAIL_TRIAGE_RULES_FILE", "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        return parse_rule_set(read_private_json(path, "EMAIL_TRIAGE_RULES_FILE"))
    except TriageValidationError as error:
        raise ConfigurationError("EMAIL_TRIAGE_RULES_FILE contains invalid rules") from error


@dataclass(frozen=True, slots=True)
class TriageHistorySettings:
    database_path: Path
    log_level: int

    @classmethod
    def from_env(cls) -> TriageHistorySettings:
        level, _level_name = read_log_level()
        return cls(
            database_path=read_file_path("DATABASE_PATH", "./data/telemetry.db"),
            log_level=level,
        )


@dataclass(frozen=True, slots=True)
class BackfillSettings:
    triage: MailboxTriageSettings
    max_messages: int

    @classmethod
    def from_env(cls) -> BackfillSettings:
        if not read_bool("GMAIL_TRIAGE_BACKFILL_ENABLED", "false"):
            raise ConfigurationError(
                "GMAIL_TRIAGE_BACKFILL_ENABLED must be true for historical backfill"
            )
        max_messages = read_positive_int("GMAIL_TRIAGE_BACKFILL_MAX_MESSAGES", "5000")
        if max_messages > 10_000:
            raise ConfigurationError("GMAIL_TRIAGE_BACKFILL_MAX_MESSAGES must not exceed 10000")
        return cls(
            triage=MailboxTriageSettings.from_env(),
            max_messages=max_messages,
        )
