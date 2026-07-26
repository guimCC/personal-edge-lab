import threading

import pytest

from personal_edge_lab.apps.telegram_bot.polling import TelegramPollingLoop
from personal_edge_lab.infrastructure.telegram.bot_api import TelegramApiError


class UnusedSource:
    def get_updates(self, *, offset: int | None, timeout_seconds: int):
        raise AssertionError((offset, timeout_seconds))


def test_offset_advances_only_after_successful_handling() -> None:
    handled: list[int] = []
    polling = TelegramPollingLoop(
        source=UnusedSource(),
        handle_update=lambda update: handled.append(update["update_id"]),
        stop_event=threading.Event(),
        poll_timeout_seconds=25,
    )

    polling._process([{"update_id": 8}, {"update_id": 9}])

    assert handled == [8, 9]
    assert polling._offset == 10


def test_failed_delivery_keeps_the_update_available_for_safe_replay() -> None:
    def fail(_update):
        raise TelegramApiError("Telegram Bot API is unavailable")

    polling = TelegramPollingLoop(
        source=UnusedSource(),
        handle_update=fail,
        stop_event=threading.Event(),
        poll_timeout_seconds=25,
    )

    with pytest.raises(TelegramApiError):
        polling._process([{"update_id": 8}])

    assert polling._offset is None


def test_failed_proactive_delivery_does_not_starve_inbound_updates() -> None:
    stop = threading.Event()
    handled: list[int] = []

    class OneUpdateSource:
        def get_updates(self, *, offset: int | None, timeout_seconds: int):
            stop.set()
            return [{"update_id": 12}]

    polling = TelegramPollingLoop(
        source=OneUpdateSource(),
        handle_update=lambda update: handled.append(update["update_id"]),
        stop_event=stop,
        poll_timeout_seconds=25,
        before_poll=lambda: (_ for _ in ()).throw(RuntimeError("delivery failure")),
    )

    polling.run()

    assert handled == [12]
    assert polling._offset == 13
