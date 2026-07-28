"""Authenticated, read-only email-triage review routes."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from personal_edge_lab.application.ports.email import EmailSourceError
from personal_edge_lab.apps.api.context import ApiContext
from personal_edge_lab.apps.api.schemas.email_triage import (
    TriageReviewContentResponse,
    TriageRunDetailResponse,
    TriageRunListResponse,
    TriageRunSummaryResponse,
)
from personal_edge_lab.domain.email_triage_review import TriageReviewError, TriageRunFilter
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage import (
    SqliteTriageRunRepository,
)
from personal_edge_lab.modules.email_triage import ReviewEmailTriageRuns

LOGGER = logging.getLogger(__name__)
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def create_email_triage_router(context: ApiContext) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/email-triage",
        tags=["email-triage"],
        dependencies=[Depends(context.require_triage_review)],
    )
    settings = context.settings

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

    @router.get(
        "/runs/{run_id}/items/{ordinal}/review",
        response_model=TriageReviewContentResponse,
    )
    def item_review(
        run_id: str,
        ordinal: int,
        response: Response,
    ) -> TriageReviewContentResponse:
        response.headers.update(NO_STORE_HEADERS)
        if not 1 <= ordinal <= 10:
            raise HTTPException(status_code=404, detail="not found")
        operation_id = uuid.uuid4().hex
        started = time.perf_counter()
        source = context.gmail_source()
        try:
            with SqliteTriageRunRepository(settings.database_path) as repository:
                service = ReviewEmailTriageRuns(repository=repository, email_source=source)
                content = service.content(run_id, ordinal)
        except TriageReviewError as error:
            LOGGER.warning(
                "email_triage_review operation_id=%s run_id=%s ordinal=%d "
                "outcome=unavailable category=%s elapsed_seconds=%.3f",
                operation_id,
                run_id,
                ordinal,
                error.category,
                time.perf_counter() - started,
            )
            status_code = 404 if error.category == "not_found" else 409
            raise HTTPException(
                status_code=status_code,
                detail="review content unavailable",
                headers=NO_STORE_HEADERS,
            ) from error
        except EmailSourceError as error:
            LOGGER.warning(
                "email_triage_review operation_id=%s run_id=%s ordinal=%d "
                "outcome=unavailable category=%s api_call_count=%d elapsed_seconds=%.3f",
                operation_id,
                run_id,
                ordinal,
                error.category.value,
                error.api_call_count,
                time.perf_counter() - started,
            )
            headers = dict(NO_STORE_HEADERS)
            if error.retry_after_seconds is not None:
                headers["Retry-After"] = str(error.retry_after_seconds)
            raise HTTPException(
                status_code=503,
                detail="review content unavailable",
                headers=headers,
            ) from error
        finally:
            close = getattr(source, "close", None)
            if close is not None:
                close()
        LOGGER.info(
            "email_triage_review operation_id=%s run_id=%s ordinal=%d outcome=success "
            "api_call_count=1 elapsed_seconds=%.3f",
            operation_id,
            run_id,
            ordinal,
            time.perf_counter() - started,
        )
        return TriageReviewContentResponse.from_domain(content)

    return router
