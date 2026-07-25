"""Air-conditioner control use cases."""

from personal_edge_lab.modules.ac_control.commands import (
    CommandConflictError,
    CommandInProgressError,
    CommandRateLimitedError,
    CommandService,
    DeviceBusyError,
)
from personal_edge_lab.modules.ac_control.policy import ExecuteCoolOnlyCommand
from personal_edge_lab.modules.ac_control.queries import (
    DEFAULT_COMMAND_HISTORY_LIMIT,
    MAX_COMMAND_HISTORY_LIMIT,
    CommandHistoryQueryError,
    ListCommandHistory,
)

__all__ = [
    "DEFAULT_COMMAND_HISTORY_LIMIT",
    "MAX_COMMAND_HISTORY_LIMIT",
    "CommandHistoryQueryError",
    "CommandConflictError",
    "CommandInProgressError",
    "CommandRateLimitedError",
    "CommandService",
    "DeviceBusyError",
    "ExecuteCoolOnlyCommand",
    "ListCommandHistory",
]
