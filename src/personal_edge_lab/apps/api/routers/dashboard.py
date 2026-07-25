"""Packaged dashboard shell route."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

DASHBOARD_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
    "form-action 'self'"
)


def create_dashboard_router(dashboard_directory: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        index = dashboard_directory / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail="dashboard unavailable")
        return FileResponse(
            index,
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": DASHBOARD_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    return router
