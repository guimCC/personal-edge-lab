"""Typed contracts shared by the Telegram owner router and its capabilities."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

COMMAND_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
NAMESPACE_PATTERN = re.compile(r"^[a-z0-9_]{1,16}$")


class TelegramGateway(Protocol):
    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]: ...

    def edit_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Mapping[str, object] | None = None,
    ) -> None: ...

    def answer_callback(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class BotCommand:
    name: str
    description: str

    def __post_init__(self) -> None:
        if COMMAND_PATTERN.fullmatch(self.name) is None:
            raise ValueError("Telegram command name is invalid")
        if not 1 <= len(self.description) <= 256:
            raise ValueError("Telegram command description is invalid")

    def as_api_payload(self) -> dict[str, str]:
        return {"command": self.name, "description": self.description}


@dataclass(frozen=True, slots=True)
class HomeAction:
    label: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("Telegram home action label cannot be blank")


@dataclass(frozen=True, slots=True)
class AuthorizedMessage:
    update_id: int
    chat_id: int
    text: str


@dataclass(frozen=True, slots=True)
class AuthorizedCallback:
    query_id: str
    chat_id: int
    message_id: int


class TelegramCapability(Protocol):
    @property
    def namespace(self) -> str: ...

    @property
    def commands(self) -> tuple[BotCommand, ...]: ...

    @property
    def home_action(self) -> HomeAction: ...

    @property
    def legacy_callback_actions(self) -> frozenset[str]: ...

    def handle_command(self, command: str, message: AuthorizedMessage) -> None: ...

    def open_from_home(self, callback: AuthorizedCallback) -> None: ...

    def handle_callback(self, action: str, callback: AuthorizedCallback) -> None: ...


def validate_namespace(value: str) -> str:
    if NAMESPACE_PATTERN.fullmatch(value) is None:
        raise ValueError("Telegram capability namespace is invalid")
    return value
