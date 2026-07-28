"""Authenticated, message-centric email-triage workspace routes."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from personal_edge_lab.apps.api.context import ApiContext
from personal_edge_lab.apps.api.schemas.email_triage import (
    TriageMessageDetailResponse,
    TriageMessageListResponse,
    TriageMessageSummaryResponse,
    TriageRunDetailResponse,
    TriageRunListResponse,
    TriageRunSummaryResponse,
)
from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_messages import (
    TriageMessageCursor,
    TriageMessageFilter,
    TriageMessageValidationError,
)
from personal_edge_lab.domain.email_triage_review import TriageRunFilter
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage import (
    SqliteTriageRunRepository,
)

NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def create_email_triage_router(context: ApiContext) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/email-triage",
        tags=["email-triage"],
        dependencies=[Depends(context.require_triage_workspace)],
    )
    settings = context.settings

    @router.get("/messages", response_model=TriageMessageListResponse)
    def recent_messages(
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        status: TriageMessageFilter = TriageMessageFilter.ALL,
        label: str = "all",
        cursor: str | None = None,
    ) -> TriageMessageListResponse:
        response.headers.update(NO_STORE_HEADERS)
        selected_label = _parse_label(label)
        decoded_cursor = _decode_cursor(cursor)
        with SqliteTriageRunRepository(settings.database_path) as repository:
            page = repository.message_page(
                limit=limit,
                message_filter=status,
                label=selected_label,
                cursor=decoded_cursor,
            )
        return TriageMessageListResponse(
            count=len(page.items),
            limit=limit,
            status=status,
            label=selected_label.value if selected_label is not None else None,
            next_cursor=_encode_cursor(page.next_cursor),
            items=[TriageMessageSummaryResponse.from_domain(item) for item in page.items],
        )

    @router.get("/messages/{record_id}", response_model=TriageMessageDetailResponse)
    def message_detail(record_id: str, response: Response) -> TriageMessageDetailResponse:
        response.headers.update(NO_STORE_HEADERS)
        with SqliteTriageRunRepository(settings.database_path) as repository:
            value = repository.message_detail(record_id)
        if value is None:
            raise HTTPException(status_code=404, detail="not found")
        return TriageMessageDetailResponse.from_domain(value)

    @router.get("/runs", response_model=TriageRunListResponse)
    def recent_runs(
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        status: TriageRunFilter = TriageRunFilter.ALL,
    ) -> TriageRunListResponse:
        response.headers.update(NO_STORE_HEADERS)
        with SqliteTriageRunRepository(settings.database_path) as repository:
            values = repository.review_recent(limit=limit, run_filter=status)
        return TriageRunListResponse(
            count=len(values),
            limit=limit,
            status=status,
            items=[TriageRunSummaryResponse.from_domain(value) for value in values],
        )

    @router.get("/runs/{run_id}", response_model=TriageRunDetailResponse)
    def run_detail(
        run_id: str,
        response: Response,
    ) -> TriageRunDetailResponse:
        response.headers.update(NO_STORE_HEADERS)
        with SqliteTriageRunRepository(settings.database_path) as repository:
            value = repository.get(run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="not found")
        return TriageRunDetailResponse.from_domain(value)

    return router


def _parse_label(value: str) -> TriageLabel | None:
    if value == "all":
        return None
    try:
        return TriageLabel(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="invalid label filter") from error


def _encode_cursor(cursor: TriageMessageCursor | None) -> str | None:
    if cursor is None:
        return None
    payload = json.dumps(
        [cursor.received_at.isoformat(), cursor.record_id],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> TriageMessageCursor | None:
    if value is None:
        return None
    if not value or len(value) > 512:
        raise HTTPException(status_code=422, detail="invalid message cursor")
    try:
        padded = value + "=" * (-len(value) % 4)
        timestamp, record_id = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return TriageMessageCursor(
            received_at=datetime.fromisoformat(timestamp),
            record_id=record_id,
        )
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        TriageMessageValidationError,
    ) as error:
        raise HTTPException(status_code=422, detail="invalid message cursor") from error
