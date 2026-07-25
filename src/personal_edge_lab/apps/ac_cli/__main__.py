"""AC CLI composition root and entry point."""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections.abc import Sequence
from typing import TextIO

import httpx

from personal_edge_lab.apps.ac_cli.config import ConfigurationError, Settings
from personal_edge_lab.domain.ac import (
    AcState,
    CommandExecution,
    CommandOutcome,
    ValidationError,
)
from personal_edge_lab.infrastructure.esp32.ac_controller import AcCommandClient
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.home import CommandService

EXIT_BY_OUTCOME = {
    CommandOutcome.CONFIRMED_SUCCESS: 0,
    CommandOutcome.REJECTED_LOCALLY: 2,
    CommandOutcome.NODE_UNREACHABLE: 3,
    CommandOutcome.TIMEOUT_UNKNOWN: 4,
    CommandOutcome.RESPONSE_UNKNOWN: 4,
    CommandOutcome.NODE_REPORTED_FAILURE: 5,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m personal_edge_lab.apps.ac_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="transmit a complete AC state")
    set_parser.add_argument("--power")
    set_parser.add_argument("--temperature")
    set_parser.add_argument("--mode")
    set_parser.add_argument("--fan")
    set_parser.add_argument("--vertical-vane")

    subparsers.add_parser("off", help="transmit the ESP32 power-off command")

    history_parser = subparsers.add_parser("history", help="show recent command attempts")
    history_parser.add_argument("--limit", type=int, default=20)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    transport: httpx.BaseTransport | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=stderr)
        return 2

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        run_migrations(settings.database_path)
        with SqliteCommandAuditRepository(settings.database_path) as audit_repository:
            if args.command == "history":
                return _show_history(
                    audit_repository,
                    args.limit,
                    stdout=stdout,
                    stderr=stderr,
                )

            with AcCommandClient(
                base_url=settings.node_base_url,
                timeout_seconds=settings.command_timeout_seconds,
                transport=transport,
            ) as controller:
                service = CommandService(
                    device_id=settings.device_id,
                    controller=controller,
                    audit_repository=audit_repository,
                )
                if args.command == "set":
                    execution = _run_set(args, service, stdout=stdout)
                else:
                    print('Command: {"power":false}', file=stdout)
                    execution = service.power_off()
    except (OSError, sqlite3.Error) as error:
        print(f"Local error: {error}", file=stderr)
        return 1

    return _show_result(execution, stdout=stdout, stderr=stderr)


def _run_set(
    args: argparse.Namespace,
    service: CommandService,
    *,
    stdout: TextIO,
) -> CommandExecution:
    attempted_payload = {
        "power": args.power,
        "temperature_c": args.temperature,
        "mode": args.mode,
        "fan": args.fan,
        "vertical_vane": args.vertical_vane,
    }
    try:
        state = AcState.from_values(
            power=args.power,
            temperature_c=args.temperature,
            mode=args.mode,
            fan=args.fan,
            vertical_vane=args.vertical_vane,
        )
    except ValidationError as error:
        return service.reject(
            command_type="set_state",
            attempted_payload=attempted_payload,
            message=str(error),
        )

    print(f"Command: {state.to_json()}", file=stdout)
    return service.set_state(state)


def _show_result(
    execution: CommandExecution,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    result = execution.result
    output = stdout if result.outcome is CommandOutcome.CONFIRMED_SUCCESS else stderr
    print(f"Command {execution.command_id}: {result.outcome.value}", file=output)
    if result.http_status is not None:
        print(f"HTTP status: {result.http_status}", file=output)
    if result.error_message:
        print(f"Reason: {result.error_message}", file=output)
    return EXIT_BY_OUTCOME[result.outcome]


def _show_history(
    audit_repository: SqliteCommandAuditRepository,
    limit: int,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if not 1 <= limit <= 100:
        print("--limit must be from 1 through 100", file=stderr)
        return 2
    entries = audit_repository.history(limit=limit)
    if not entries:
        print("No AC command attempts recorded.", file=stdout)
        return 0
    print("ID  REQUESTED_AT_UTC                    OUTCOME                 COMMAND", file=stdout)
    for entry in entries:
        print(
            f"{entry.id:<3} {entry.requested_at_utc.isoformat():<35} "
            f"{entry.outcome.value:<23} {entry.command_type}",
            file=stdout,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
