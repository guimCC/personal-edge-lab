"""Small, token-safe client for the Telegram Bot API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx


class TelegramApiError(RuntimeError):
    """A sanitized Telegram transport or protocol failure."""


class TelegramBotClient:
    def __init__(
        self,
        *,
        token: str,
        request_timeout_seconds: float = 10,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=request_timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> TelegramBotClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_me(self) -> Mapping[str, Any]:
        return self._mapping_result("getMe")

    def get_webhook_info(self) -> Mapping[str, Any]:
        return self._mapping_result("getWebhookInfo")

    def set_commands(self, commands: Sequence[Mapping[str, str]]) -> None:
        self._call("setMyCommands", {"commands": list(commands)})

    def get_updates(
        self,
        *,
        offset: int | None,
        timeout_seconds: int,
    ) -> list[Mapping[str, Any]]:
        payload: dict[str, object] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call(
            "getUpdates",
            payload,
            timeout_seconds=timeout_seconds + 5,
        )
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise TelegramApiError("Telegram returned an invalid updates response")
        return result

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._mapping_result("sendMessage", payload)

    def edit_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Mapping[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self._call("editMessageText", payload)

    def answer_callback(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        payload: dict[str, object] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text is not None:
            payload["text"] = text
        self._call("answerCallbackQuery", payload)

    def _mapping_result(
        self,
        method: str,
        payload: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        result = self._call(method, payload)
        if not isinstance(result, dict):
            raise TelegramApiError(f"Telegram returned an invalid {method} response")
        return result

    def _call(
        self,
        method: str,
        payload: Mapping[str, object] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        try:
            response = self._client.post(
                method,
                json=dict(payload or {}),
                timeout=timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise TelegramApiError("Telegram Bot API is unavailable") from error
        try:
            body = response.json()
        except ValueError as error:
            raise TelegramApiError("Telegram returned a non-JSON response") from error
        if not isinstance(body, dict) or body.get("ok") is not True:
            error_code = body.get("error_code") if isinstance(body, dict) else None
            suffix = f" (code {error_code})" if isinstance(error_code, int) else ""
            raise TelegramApiError(f"Telegram rejected the request{suffix}")
        return body.get("result")
