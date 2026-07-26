"""Casadaqui owner-only Telegram bot composition root."""

from __future__ import annotations

import logging
import signal
import sqlite3
import threading
from collections.abc import Mapping

import httpx

from personal_edge_lab import __version__
from personal_edge_lab.apps.logging_config import configure_logging
from personal_edge_lab.apps.telegram_bot.capabilities.ac import (
    AcCapability,
    PanelState,
    latest_requested_state,
)
from personal_edge_lab.apps.telegram_bot.capabilities.status import (
    StatusCapability,
    TelegramStatusSnapshot,
)
from personal_edge_lab.apps.telegram_bot.config import ConfigurationError, Settings
from personal_edge_lab.apps.telegram_bot.owner_bot import OwnerBot
from personal_edge_lab.apps.telegram_bot.polling import TelegramPollingLoop
from personal_edge_lab.domain.ac import CommandExecution, CommandRequestContext
from personal_edge_lab.infrastructure.esp32.ac_controller import AcCommandClient
from personal_edge_lab.infrastructure.persistence.sqlite.alert_queries import (
    SqliteAlertQueryRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.collector_status import (
    SqliteCollectorStatusRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.infrastructure.telegram.bot_api import (
    TelegramApiError,
    TelegramBotClient,
)
from personal_edge_lab.modules.ac_control import CommandService, ExecuteCoolOnlyCommand
from personal_edge_lab.modules.platform_status import GetPlatformHealth

LOGGER = logging.getLogger(__name__)


def main(*, stop_event: threading.Event | None = None) -> int:
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
        LOGGER.error("Invalid configuration: %s", error)
        return 2

    configure_logging(settings.log_level)
    # httpx includes request URLs in INFO logs; Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    shutdown = stop_event or threading.Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s; requesting shutdown", signal.Signals(signum).name)
        shutdown.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    def execute_command(
        context: CommandRequestContext,
        command_type: str,
        state_payload: Mapping[str, object] | None,
    ) -> CommandExecution:
        with (
            SqliteCommandAuditRepository(settings.database_path) as repository,
            AcCommandClient(
                base_url=settings.node_base_url,
                timeout_seconds=settings.command_timeout_seconds,
            ) as controller,
        ):
            return ExecuteCoolOnlyCommand(
                service=CommandService(
                    device_id=settings.ac_device_id,
                    controller=controller,
                    audit_repository=repository,
                    context=context,
                )
            ).execute(command_type=command_type, state_payload=state_payload)

    def requested_state() -> PanelState:
        with SqliteCommandAuditRepository(settings.database_path) as repository:
            return latest_requested_state(repository.history(limit=100))

    def platform_status() -> TelegramStatusSnapshot:
        try:
            response = httpx.get(
                f"http://127.0.0.1:{settings.api_port}/health/live",
                timeout=2,
            )
            api_reachable = response.status_code == 200
        except httpx.HTTPError:
            api_reachable = False
        platform = GetPlatformHealth(
            telemetry_repository_factory=lambda: SqliteTelemetryRepository(settings.database_path),
            collector_repository_factory=lambda: SqliteCollectorStatusRepository(
                settings.database_path
            ),
            alert_repository_factory=lambda: SqliteAlertQueryRepository(settings.database_path),
            device_id=settings.telemetry_device_id,
            telemetry_stale_after_seconds=settings.telemetry_stale_after_seconds,
            collector_stale_after_seconds=settings.collector_stale_after_seconds,
            evaluator_stale_after_seconds=settings.alert_evaluator_stale_after_seconds,
        ).execute()
        return TelegramStatusSnapshot(
            platform=platform,
            api_reachable=api_reachable,
            version=__version__,
        )

    try:
        run_migrations(settings.database_path)
        with TelegramBotClient(
            token=settings.read_token(),
            request_timeout_seconds=settings.poll_timeout_seconds + 5,
        ) as telegram:
            webhook = telegram.get_webhook_info()
            if webhook.get("url"):
                raise TelegramApiError(
                    "a Telegram webhook is configured; remove it before using long polling"
                )
            bot = telegram.get_me()
            username = bot.get("username")
            LOGGER.info(
                "Connected to Telegram bot%s",
                f" @{username}" if isinstance(username, str) else "",
            )
            status_capability = StatusCapability(
                gateway=telegram,
                status_provider=platform_status,
                version=__version__,
            )
            ac_capability = AcCapability(
                gateway=telegram,
                owner_user_id=settings.owner_user_id,
                execute_command=execute_command,
                state_provider=requested_state,
                command_rate_limit=settings.command_rate_limit_per_minute,
                command_timeout_seconds=settings.command_timeout_seconds,
            )
            owner_bot = OwnerBot(
                gateway=telegram,
                owner_user_id=settings.owner_user_id,
                capabilities=(status_capability, ac_capability),
            )
            telegram.set_commands([command.as_api_payload() for command in owner_bot.commands])
            TelegramPollingLoop(
                source=telegram,
                handle_update=owner_bot.handle_update,
                stop_event=shutdown,
                poll_timeout_seconds=settings.poll_timeout_seconds,
            ).run()
    except (OSError, sqlite3.Error, TelegramApiError) as error:
        LOGGER.error("Telegram bot stopped after an operational failure: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
