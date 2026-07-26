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
    assert caught.value.category == "http_status"


def test_rate_limit_exposes_only_structured_retry_metadata() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": f"wait because {TOKEN}",
                "parameters": {"retry_after": 17},
            },
        )

    with (
        TelegramBotClient(token=TOKEN, transport=httpx.MockTransport(handler)) as client,
        pytest.raises(TelegramApiError) as caught,
    ):
        client.get_me()

    assert TOKEN not in str(caught.value)
    assert caught.value.category == "rate_limited"
    assert caught.value.retry_after_seconds == 17


def test_messages_use_native_html_and_inline_button_styles() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 12}})

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "Enviar ajuste",
                    "callback_data": "send",
                    "style": "success",
                }
            ]
        ]
    }
    with TelegramBotClient(token=TOKEN, transport=httpx.MockTransport(handler)) as client:
        client.send_message(
            chat_id=112233,
            text="<b>AIRE ACONDICIONADO</b>",
            reply_markup=keyboard,
        )

    assert observed == {
        "chat_id": 112233,
        "text": "<b>AIRE ACONDICIONADO</b>",
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }


@pytest.mark.parametrize(
    ("method", "description"),
    [
        (
            "edit",
            "Bad Request: message is not modified: specified new message content "
            "and reply markup are exactly the same",
        ),
        (
            "callback",
            "Bad Request: query is too old and response timeout expired or query ID is invalid",
        ),
    ],
)
def test_idempotent_telegram_noops_do_not_poison_the_update_offset(
    method: str,
    description: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": description,
            },
        )

    with TelegramBotClient(token=TOKEN, transport=httpx.MockTransport(handler)) as client:
        if method == "edit":
            client.edit_message(
                chat_id=112233,
                message_id=10,
                text="Sin cambios",
            )
        else:
            client.answer_callback(callback_query_id="expired-query")
