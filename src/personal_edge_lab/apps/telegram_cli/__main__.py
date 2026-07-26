"""Provision Casadaqui's token and discover the private owner user ID."""

from __future__ import annotations

import argparse
import contextlib
import getpass
import logging
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from personal_edge_lab.apps.configuration import read_file_path
from personal_edge_lab.infrastructure.telegram.bot_api import (
    TelegramApiError,
    TelegramBotClient,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m personal_edge_lab.apps.telegram_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("set-token", help="validate and store the Telegram bot token")
    subparsers.add_parser(
        "discover-owner",
        help="print the private Telegram user ID from a recent message",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = build_parser().parse_args(argv)
    token_file = read_file_path(
        "TELEGRAM_BOT_TOKEN_FILE",
        "./secrets/telegram-bot.token",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "set-token":
        return _set_token(token_file, stdout=stdout, stderr=stderr)
    return _discover_owner(token_file, stdout=stdout, stderr=stderr)


def _set_token(token_file: Path, *, stdout: TextIO, stderr: TextIO) -> int:
    token = getpass.getpass("Telegram bot token: ").strip()
    if not token or any(character.isspace() for character in token):
        print("Token must be nonblank and contain no whitespace.", file=stderr)
        return 2
    try:
        with TelegramBotClient(token=token) as telegram:
            bot = telegram.get_me()
    except TelegramApiError:
        print("Telegram did not accept this token.", file=stderr)
        return 1
    _atomic_secret_write(token_file, token)
    username = bot.get("username")
    label = f"@{username}" if isinstance(username, str) else "the configured bot"
    print(f"Token validated for {label} and stored in {token_file}.", file=stdout)
    return 0


def _discover_owner(token_file: Path, *, stdout: TextIO, stderr: TextIO) -> int:
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        print("Telegram token file is not readable; run set-token first.", file=stderr)
        return 2
    try:
        with TelegramBotClient(token=token) as telegram:
            updates = telegram.get_updates(offset=None, timeout_seconds=0)
    except TelegramApiError:
        print(
            "Could not read Telegram updates. Ensure the bot service is stopped and try again.",
            file=stderr,
        )
        return 1
    for update in reversed(updates):
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            continue
        user_id = sender.get("id")
        if chat.get("type") == "private" and isinstance(user_id, int) and user_id > 0:
            username = sender.get("username")
            if isinstance(username, str):
                print(f"Private message found from @{username}.", file=stdout)
            print(f"TELEGRAM_OWNER_USER_ID={user_id}", file=stdout)
            return 0
    print(
        "No private message found. Send /start to Casadaqui_bot, then run this command again.",
        file=stderr,
    )
    return 1


def _atomic_secret_write(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(f"{value}\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        Path(temporary_name).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
