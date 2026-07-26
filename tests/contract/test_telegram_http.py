from __future__ import annotations

import json

import httpx
import pytest

from personal_edge_lab.infrastructure.telegram.bot_api import (
    TelegramApiError,
    TelegramBotClient,
)

TOKEN = "123456:never-log-this-token"


def test_long_poll_uses_bounded_update_types_and_offset() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 9}]})

    with TelegramBotClient(token=TOKEN, transport=httpx.MockTransport(handler)) as client:
        updates = client.get_updates(offset=9, timeout_seconds=25)

    assert updates == [{"update_id": 9}]
    assert observed == {
        "offset": 9,
        "timeout": 25,
        "allowed_updates": ["message", "callback_query"],
    }


def test_api_failures_never_expose_the_bot_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"ok": False, "error_code": 401, "description": f"bad {TOKEN}"},
        )

    with (
        TelegramBotClient(token=TOKEN, transport=httpx.MockTransport(handler)) as client,
        pytest.raises(TelegramApiError) as caught,
    ):
        client.get_me()

    assert TOKEN not in str(caught.value)
    assert str(caught.value) == "Telegram rejected the request (code 401)"
