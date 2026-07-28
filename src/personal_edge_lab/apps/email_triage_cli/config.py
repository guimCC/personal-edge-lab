"""Environment configuration for bounded read-only Gmail diagnostics."""

from __future__ import annotations

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
)
from personal_edge_lab.apps.gmail_configuration import (
    GmailAuthorizationSettings as GmailAuthorizationSettings,
)
from personal_edge_lab.apps.gmail_configuration import (
    GmailFetchSettings,
)


@dataclass(frozen=True, slots=True)
class MailboxTriageSettings:
    gmail: GmailFetchSettings
    completion: CompletionSettings
    langfuse: LangfuseSettings
    database_path: Path
    log_level: int

    @classmethod
    def from_env(cls) -> MailboxTriageSettings:
        if not read_bool("GMAIL_TRIAGE_ENABLED", "false"):
            raise ConfigurationError("GMAIL_TRIAGE_ENABLED must be true for triage")
        gmail = GmailFetchSettings.from_env()
        completion = CompletionSettings.from_env()
        langfuse = LangfuseSettings.from_env()
        database_path = read_file_path("DATABASE_PATH", "./data/telemetry.db")
        level, _level_name = read_log_level()
        return cls(
            gmail=gmail,
            completion=completion,
            langfuse=langfuse,
            database_path=database_path,
            log_level=level,
        )


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
