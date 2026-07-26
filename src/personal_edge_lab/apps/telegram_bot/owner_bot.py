"""Owner authorization, home navigation, and capability routing for Casadaqui."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from personal_edge_lab.apps.telegram_bot.contracts import (
    AuthorizedCallback,
    AuthorizedMessage,
    BotCommand,
    TelegramCapability,
    TelegramGateway,
    validate_namespace,
)

HELP_COMMAND = BotCommand("help", "Mostrar el menú principal")
HOME_TEXT = (
    "🏠 <b>Casadaqui · Personal Edge Lab</b>\n\n"
    "Consulta y controla tus capacidades personales desde un único lugar.\n\n"
    "Elige una opción:"
)


class OwnerBot:
    def __init__(
        self,
        *,
        gateway: TelegramGateway,
        owner_user_id: int,
        capabilities: Sequence[TelegramCapability],
    ) -> None:
        if owner_user_id <= 0:
            raise ValueError("Telegram owner user ID must be positive")
        self._gateway = gateway
        self._owner_user_id = owner_user_id
        self._capabilities = tuple(capabilities)
        self._by_namespace: dict[str, TelegramCapability] = {}
        self._by_command: dict[str, TelegramCapability] = {}
        self._legacy_by_action: dict[str, TelegramCapability] = {}
        for capability in self._capabilities:
            namespace = validate_namespace(capability.namespace)
            if namespace in self._by_namespace:
                raise ValueError(f"duplicate Telegram capability namespace: {namespace}")
            self._by_namespace[namespace] = capability
            for command in capability.commands:
                if command.name in self._by_command or command.name in {"start", "help"}:
                    raise ValueError(f"duplicate Telegram command: {command.name}")
                self._by_command[command.name] = capability
            for action in capability.legacy_callback_actions:
                if action in self._legacy_by_action:
                    raise ValueError(f"duplicate legacy Telegram callback action: {action}")
                self._legacy_by_action[action] = capability

    @property
    def commands(self) -> tuple[BotCommand, ...]:
        return tuple(
            command for capability in self._capabilities for command in capability.commands
        ) + (HELP_COMMAND,)

    def handle_update(self, update: Mapping[str, Any]) -> None:
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(update, message)
            return
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._handle_callback(callback)

    def _handle_message(
        self,
        update: Mapping[str, Any],
        message: Mapping[str, Any],
    ) -> None:
        if _private_identity(message) != (self._owner_user_id, self._owner_user_id):
            return
        text = message.get("text")
        update_id = update.get("update_id")
        if not isinstance(text, str) or not isinstance(update_id, int):
            return
        command = _command_name(text)
        if command is None:
            return
        authorized = AuthorizedMessage(
            update_id=update_id,
            chat_id=self._owner_user_id,
            text=text,
        )
        if command in {"start", "help"}:
            self._send_home()
            return
        capability = self._by_command.get(command)
        if capability is None:
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text="No conozco ese comando todavía.",
                reply_markup=self._home_keyboard(),
            )
            return
        capability.handle_command(command, authorized)

    def _handle_callback(self, callback: Mapping[str, Any]) -> None:
        callback_id = callback.get("id")
        message = callback.get("message")
        sender = callback.get("from")
        data = callback.get("data")
        if (
            not isinstance(callback_id, str)
            or not isinstance(message, dict)
            or not isinstance(sender, dict)
            or not isinstance(data, str)
        ):
            return
        if _private_identity(message, sender=sender) != (
            self._owner_user_id,
            self._owner_user_id,
        ):
            self._gateway.answer_callback(
                callback_query_id=callback_id,
                text="Este control es privado.",
                show_alert=True,
            )
            return
        message_id = message.get("message_id")
        if not isinstance(message_id, int):
            return
        authorized = AuthorizedCallback(
            query_id=callback_id,
            chat_id=self._owner_user_id,
            message_id=message_id,
        )
        try:
            self._dispatch_callback(data, authorized)
        except ValueError:
            self._gateway.answer_callback(
                callback_query_id=callback_id,
                text="Este control no es válido o ha caducado.",
                show_alert=True,
            )

    def _dispatch_callback(
        self,
        data: str,
        callback: AuthorizedCallback,
    ) -> None:
        if data.startswith("home:"):
            namespace = data.removeprefix("home:")
            capability = self._by_namespace.get(namespace)
            if capability is None:
                raise ValueError("unknown Telegram home action")
            capability.open_from_home(callback)
            return
        namespace, separator, action = data.partition(":")
        if separator:
            capability = self._by_namespace.get(namespace)
            if capability is not None:
                capability.handle_callback(action, callback)
                return
        legacy_action = data.split(":", maxsplit=1)[0]
        capability = self._legacy_by_action.get(legacy_action)
        if capability is None:
            raise ValueError("unknown Telegram callback")
        capability.handle_callback(data, callback)

    def _send_home(self) -> None:
        self._gateway.send_message(
            chat_id=self._owner_user_id,
            text=HOME_TEXT,
            reply_markup=self._home_keyboard(),
        )

    def _home_keyboard(self) -> Mapping[str, object]:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": capability.home_action.label,
                        "callback_data": f"home:{capability.namespace}",
                    }
                ]
                for capability in self._capabilities
            ]
        }


def _command_name(text: str) -> str | None:
    first = text.strip().split(maxsplit=1)[0]
    if not first.startswith("/"):
        return None
    command = first[1:].split("@", maxsplit=1)[0].lower()
    return command or None


def _private_identity(
    message: Mapping[str, Any],
    *,
    sender: Mapping[str, Any] | None = None,
) -> tuple[int, int] | None:
    chat = message.get("chat")
    author = sender or message.get("from")
    if not isinstance(chat, dict) or not isinstance(author, dict):
        return None
    chat_id = chat.get("id")
    user_id = author.get("id")
    if (
        chat.get("type") != "private"
        or not isinstance(chat_id, int)
        or not isinstance(user_id, int)
    ):
        return None
    return user_id, chat_id
