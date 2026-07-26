"""Resilient long-polling lifecycle for Telegram updates."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from personal_edge_lab.infrastructure.telegram.bot_api import TelegramApiError

LOGGER = logging.getLogger(__name__)


class UpdateSource(Protocol):
    def get_updates(
        self,
        *,
        offset: int | None,
        timeout_seconds: int,
    ) -> list[Mapping[str, Any]]: ...


class TelegramPollingLoop:
    def __init__(
        self,
        *,
        source: UpdateSource,
        handle_update: Callable[[Mapping[str, Any]], None],
        stop_event: threading.Event,
        poll_timeout_seconds: int,
        retry_delay_seconds: float = 2,
        before_poll: Callable[[], None] | None = None,
    ) -> None:
        self._source = source
        self._handle_update = handle_update
        self._stop_event = stop_event
        self._poll_timeout_seconds = poll_timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._before_poll = before_poll
        self._offset: int | None = None

    def run(self) -> None:
        LOGGER.info("Casadaqui owner operations bot started")
        try:
            while not self._stop_event.is_set():
                if self._before_poll is not None:
                    try:
                        self._before_poll()
                    except Exception:
                        LOGGER.warning(
                            "Proactive notification delivery cycle failed; "
                            "continuing with inbound updates"
                        )
                try:
                    updates = self._source.get_updates(
                        offset=self._offset,
                        timeout_seconds=self._poll_timeout_seconds,
                    )
                    self._process(updates)
                except TelegramApiError as error:
                    LOGGER.warning("Telegram polling interrupted: %s", error)
                    self._stop_event.wait(self._retry_delay_seconds)
        finally:
            LOGGER.info("Casadaqui owner operations bot stopped")

    def _process(self, updates: list[Mapping[str, Any]]) -> None:
        for update in updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                LOGGER.warning("Ignoring Telegram update without a valid update_id")
                continue
            self._handle_update(update)
            self._offset = update_id + 1
