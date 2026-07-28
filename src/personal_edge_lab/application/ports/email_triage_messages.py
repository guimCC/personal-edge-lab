"""Narrow query port for the durable message-centric workspace."""

from __future__ import annotations

from typing import Protocol

from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_messages import (
    TriageMessageCursor,
    TriageMessageDetail,
    TriageMessageFilter,
    TriageMessagePage,
)


class TriageMessageQueryRepository(Protocol):
    def message_page(
        self,
        *,
        limit: int,
        message_filter: TriageMessageFilter,
        label: TriageLabel | None,
        cursor: TriageMessageCursor | None,
    ) -> TriageMessagePage: ...

    def message_detail(self, record_id: str) -> TriageMessageDetail | None: ...

    def close(self) -> None: ...
