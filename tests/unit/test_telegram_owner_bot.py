from __future__ import annotations

from typing import Any

import pytest

from personal_edge_lab.apps.telegram_bot.contracts import (
    AuthorizedCallback,
    AuthorizedMessage,
    BotCommand,
    HomeAction,
)
from personal_edge_lab.apps.telegram_bot.owner_bot import OwnerBot

OWNER_ID = 112233


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.answered: list[dict[str, Any]] = []

    def send_message(self, **payload: Any) -> dict[str, Any]:
        self.sent.append(payload)
        return {"message_id": 1}

    def edit_message(self, **payload: Any) -> None:
        self.edited.append(payload)

    def answer_callback(self, **payload: Any) -> None:
        self.answered.append(payload)


class FakeCapability:
    def __init__(
        self,
        namespace: str,
        commands: tuple[BotCommand, ...],
        label: str,
        *,
        legacy: frozenset[str] = frozenset(),
    ) -> None:
        self.namespace = namespace
        self.commands = commands
        self.home_action = HomeAction(label)
        self.legacy_callback_actions = legacy
        self.command_calls: list[tuple[str, AuthorizedMessage]] = []
        self.home_calls: list[AuthorizedCallback] = []
        self.callback_calls: list[tuple[str, AuthorizedCallback]] = []

    def handle_command(self, command: str, message: AuthorizedMessage) -> None:
        self.command_calls.append((command, message))

    def open_from_home(self, callback: AuthorizedCallback) -> None:
        self.home_calls.append(callback)

    def handle_callback(self, action: str, callback: AuthorizedCallback) -> None:
        self.callback_calls.append((action, callback))


def message_update(
    text: str,
    *,
    user_id: int = OWNER_ID,
    chat_id: int | None = None,
    chat_type: str = "private",
    update_id: int = 7,
) -> dict[str, Any]:
    selected_chat_id = user_id if chat_id is None else chat_id
    return {
        "update_id": update_id,
        "message": {
            "message_id": 10,
            "text": text,
            "from": {"id": user_id},
            "chat": {"id": selected_chat_id, "type": chat_type},
        },
    }


def callback_update(
    data: str,
    *,
    user_id: int = OWNER_ID,
    chat_id: int | None = None,
) -> dict[str, Any]:
    selected_chat_id = user_id if chat_id is None else chat_id
    return {
        "update_id": 8,
        "callback_query": {
            "id": "query-1",
            "data": data,
            "from": {"id": user_id},
            "message": {
                "message_id": 10,
                "chat": {"id": selected_chat_id, "type": "private"},
            },
        },
    }


def capabilities() -> tuple[FakeCapability, FakeCapability]:
    status = FakeCapability(
        "status",
        (BotCommand("status", "Ver estado"),),
        "🧭 Estado",
        legacy=frozenset({"refresh_status"}),
    )
    ac = FakeCapability(
        "ac",
        (
            BotCommand("ac", "Abrir aire"),
            BotCommand("off", "Apagar aire"),
        ),
        "❄️ Aire acondicionado",
        legacy=frozenset({"panel"}),
    )
    return status, ac


def test_home_and_native_commands_come_from_the_capability_registry() -> None:
    gateway = FakeGateway()
    status, ac = capabilities()
    bot = OwnerBot(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        capabilities=(status, ac),
    )

    bot.handle_update(message_update("/start"))

    assert "Casadaqui · Personal Edge Lab" in gateway.sent[-1]["text"]
    keyboard = gateway.sent[-1]["reply_markup"]["inline_keyboard"]
    assert keyboard == [
        [{"text": "🧭 Estado", "callback_data": "home:status"}],
        [{"text": "❄️ Aire acondicionado", "callback_data": "home:ac"}],
    ]
    assert [command.as_api_payload() for command in bot.commands] == [
        {"command": "status", "description": "Ver estado"},
        {"command": "ac", "description": "Abrir aire"},
        {"command": "off", "description": "Apagar aire"},
        {"command": "help", "description": "Mostrar el menú principal"},
    ]


def test_owner_router_handles_commands_home_namespaces_and_legacy_callbacks() -> None:
    gateway = FakeGateway()
    status, ac = capabilities()
    bot = OwnerBot(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        capabilities=(status, ac),
    )

    bot.handle_update(message_update("/status@Casadaqui_bot ignored", update_id=91))
    bot.handle_update(callback_update("home:status"))
    bot.handle_update(callback_update("status:refresh"))
    bot.handle_update(callback_update("refresh_status"))

    assert status.command_calls[0][0] == "status"
    assert status.command_calls[0][1].update_id == 91
    assert status.home_calls[0].message_id == 10
    assert [call[0] for call in status.callback_calls] == ["refresh", "refresh_status"]
    assert ac.command_calls == []


def test_router_centralizes_private_owner_authorization() -> None:
    gateway = FakeGateway()
    status, ac = capabilities()
    bot = OwnerBot(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        capabilities=(status, ac),
    )

    bot.handle_update(message_update("/ac", user_id=999))
    bot.handle_update(
        message_update(
            "/status",
            chat_id=-1001,
            chat_type="group",
        )
    )
    bot.handle_update(callback_update("home:ac", user_id=999))

    assert gateway.sent == []
    assert status.command_calls == []
    assert ac.command_calls == []
    assert gateway.answered[-1] == {
        "callback_query_id": "query-1",
        "text": "Este control es privado.",
        "show_alert": True,
    }


def test_unknown_commands_show_home_but_free_text_remains_ignored() -> None:
    gateway = FakeGateway()
    status, ac = capabilities()
    bot = OwnerBot(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        capabilities=(status, ac),
    )

    bot.handle_update(message_update("haz un triaje de mi email"))
    assert gateway.sent == []

    bot.handle_update(message_update("/unknown"))

    assert gateway.sent[-1]["text"] == "No conozco ese comando todavía."
    assert gateway.sent[-1]["reply_markup"]["inline_keyboard"]


def test_incomplete_updates_are_ignored_and_invalid_callbacks_are_sanitized() -> None:
    gateway = FakeGateway()
    status, ac = capabilities()
    bot = OwnerBot(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        capabilities=(status, ac),
    )

    bot.handle_update({"update_id": 1, "message": {"text": "/status"}})
    bot.handle_update({"update_id": 2, "callback_query": {"id": "missing-data"}})

    assert gateway.sent == []
    assert gateway.answered == []

    bot.handle_update(callback_update("missing:unknown"))

    assert gateway.answered[-1] == {
        "callback_query_id": "query-1",
        "text": "Este control no es válido o ha caducado.",
        "show_alert": True,
    }


@pytest.mark.parametrize("duplicate", ["namespace", "command", "legacy", "reserved"])
def test_registry_rejects_ambiguous_routes(duplicate: str) -> None:
    gateway = FakeGateway()
    status, _ac = capabilities()
    other = FakeCapability(
        "status" if duplicate == "namespace" else "other",
        (
            BotCommand(
                (
                    "status"
                    if duplicate == "command"
                    else "help"
                    if duplicate == "reserved"
                    else "other"
                ),
                "Otra capacidad",
            ),
        ),
        "Otra",
        legacy=frozenset({"refresh_status"} if duplicate == "legacy" else set()),
    )

    with pytest.raises(ValueError, match="duplicate"):
        OwnerBot(
            gateway=gateway,
            owner_user_id=OWNER_ID,
            capabilities=(status, other),
        )
