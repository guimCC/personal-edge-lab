"""Authenticated AC audit and command routes."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from personal_edge_lab.apps.api.context import ApiContext
from personal_edge_lab.apps.api.schemas import (
    AcCommandRequest,
    AcCommandResponse,
    CommandAuditResponse,
    CommandHistoryResponse,
)
from personal_edge_lab.apps.api.types import CommandLimit, IdempotencyKey
from personal_edge_lab.domain.ac import CommandRequestContext
from personal_edge_lab.domain.auth import AuthenticatedSession
from personal_edge_lab.infrastructure.esp32.ac_controller import AcCommandClient
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.modules.ac_control import (
    CommandConflictError,
    CommandInProgressError,
    CommandRateLimitedError,
    CommandService,
    DeviceBusyError,
    ExecuteCoolOnlyCommand,
    ListCommandHistory,
)


def create_ac_router(context: ApiContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1/ac", tags=["air conditioner"])
    settings = context.settings

    @router.get("/history", response_model=CommandHistoryResponse)
    def command_history(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(context.require_session),
        ],
        limit: CommandLimit = 20,
    ) -> CommandHistoryResponse:
        with SqliteCommandAuditRepository(settings.database_path) as repository:
            entries = ListCommandHistory(repository).execute(limit=limit)
        items = [CommandAuditResponse.from_domain(entry) for entry in entries]
        return CommandHistoryResponse(count=len(items), limit=limit, items=items)

    @router.post(
        "/commands",
        response_model=AcCommandResponse,
        responses={
            200: {"model": AcCommandResponse},
            409: {"description": "Idempotency conflict or command in progress"},
            429: {"description": "Command rate limit exceeded"},
        },
        include_in_schema=settings.ac_control_enabled,
    )
    def ac_command(
        body: AcCommandRequest,
        idempotency_key: IdempotencyKey,
        session: Annotated[
            AuthenticatedSession,
            Depends(context.require_command_csrf),
        ],
    ) -> JSONResponse:
        if not settings.ac_control_enabled:
            raise HTTPException(status_code=404, detail="not found")
        request_context = CommandRequestContext(
            actor_id=session.actor_id,
            request_source="dashboard",
            idempotency_key=idempotency_key,
            rate_limit=settings.command_rate_limit_per_minute,
            rate_window_seconds=60,
            lock_lease_seconds=settings.ac_command_timeout_seconds + 10,
        )
        controller = (
            context.ac_controller_factory()
            if context.ac_controller_factory is not None
            else AcCommandClient(
                base_url=settings.ac_node_base_url,
                timeout_seconds=settings.ac_command_timeout_seconds,
            )
        )
        should_close = context.ac_controller_factory is None
        try:
            with SqliteCommandAuditRepository(settings.database_path) as repository:
                service = CommandService(
                    device_id=settings.device_id,
                    controller=controller,
                    audit_repository=repository,
                    context=request_context,
                    clock=context.clock,
                )
                execution = ExecuteCoolOnlyCommand(service).execute(
                    command_type=body.command_type,
                    state_payload=body.state,
                )
                entry = repository.get(execution.command_id)
                if entry is None:
                    raise sqlite3.DatabaseError("command audit record was not found")
        except (CommandConflictError, CommandInProgressError, DeviceBusyError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CommandRateLimitedError as error:
            raise HTTPException(
                status_code=429,
                detail="command rate limit exceeded",
                headers={"Retry-After": str(error.retry_after_seconds)},
            ) from error
        finally:
            if should_close:
                close = getattr(controller, "close", None)
                if callable(close):
                    close()
        response = AcCommandResponse(
            audit=CommandAuditResponse.from_domain(entry),
            replayed=execution.replayed,
        )
        return JSONResponse(
            status_code=200 if execution.replayed else 201,
            content=response.model_dump(mode="json"),
        )

    return router
