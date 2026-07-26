from __future__ import annotations

import io
import stat
from typing import Any

from personal_edge_lab.apps.telegram_cli import __main__ as telegram_cli


class FakeTelegram:
    updates: list[dict[str, Any]] = []

    def __init__(self, *, token: str) -> None:
        self.token = token

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get_me(self) -> dict[str, object]:
        return {"username": "Casadaqui_bot"}

    def get_updates(self, *, offset: int | None, timeout_seconds: int):
        assert offset is None
        assert timeout_seconds == 0
        return self.updates


def test_set_token_validates_and_writes_a_mode_0600_secret(
    monkeypatch,
    tmp_path,
) -> None:
    token_file = tmp_path / "secrets/telegram-bot.token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(telegram_cli.getpass, "getpass", lambda _prompt: "123456:secret-token")
    monkeypatch.setattr(telegram_cli, "TelegramBotClient", FakeTelegram)
    stdout = io.StringIO()

    result = telegram_cli.main(["set-token"], stdout=stdout, stderr=io.StringIO())

    assert result == 0
    assert token_file.read_text(encoding="utf-8") == "123456:secret-token\n"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert "@Casadaqui_bot" in stdout.getvalue()


def test_discover_owner_prints_numeric_private_identity(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "telegram-bot.token"
    token_file.write_text("123456:secret-token\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(telegram_cli, "TelegramBotClient", FakeTelegram)
    FakeTelegram.updates = [
        {
            "update_id": 1,
            "message": {
                "from": {"id": 112233, "username": "owner"},
                "chat": {"id": 112233, "type": "private"},
            },
        }
    ]
    stdout = io.StringIO()

    result = telegram_cli.main(["discover-owner"], stdout=stdout, stderr=io.StringIO())

    assert result == 0
    assert "TELEGRAM_OWNER_USER_ID=112233" in stdout.getvalue()
