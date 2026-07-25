"""Reusable AC audit read use cases."""

from __future__ import annotations

from personal_edge_lab.application.ports.ac import CommandAuditRepository
from personal_edge_lab.domain.ac import CommandAuditEntry

DEFAULT_COMMAND_HISTORY_LIMIT = 20
MAX_COMMAND_HISTORY_LIMIT = 100


class CommandHistoryQueryError(ValueError):
    """Raised when an AC command-history query is invalid."""


class ListCommandHistory:
    def __init__(self, repository: CommandAuditRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        limit: int = DEFAULT_COMMAND_HISTORY_LIMIT,
    ) -> list[CommandAuditEntry]:
        if not 1 <= limit <= MAX_COMMAND_HISTORY_LIMIT:
            raise CommandHistoryQueryError(
                f"limit must be from 1 through {MAX_COMMAND_HISTORY_LIMIT}"
            )
        return self._repository.history(limit=limit)
