"""Application assembly: routers, static files, and the error seam."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import v1
from app.config import get_settings
from app.web import router as web_router
from app.web.templates import STATIC_DIR, templates

PROBLEM_JSON = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Logs go to stdout; the platform collects them. No files, no rotation.
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        summary="Locates the entry at which a staking plan can no longer fund its next stake.",
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # JSON is versioned; pages are not.
    app.include_router(v1.router)
    app.include_router(web_router)

    app.add_exception_handler(ValueError, _invalid_configuration)
    app.add_exception_handler(HTTPException, _http_error)
    return app


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
        media_type=PROBLEM_JSON,
    )


async def _invalid_configuration(request: Request, exc: Exception) -> Response:
    """The one translation of a domain rejection into an HTTP response.

    `StakingConfig.__post_init__` is the authoritative validator for a staking
    plan. Nothing re-implements its rules, and no route wraps the simulator in a
    `try/except` to reach this — the exception arrives here on its own.
    """
    return _problem(422, "Invalid staking configuration", str(exc))


async def _http_error(request: Request, exc: Exception) -> Response:
    """Problem+json for the JSON API, a rendered page for the browser."""
    assert isinstance(exc, HTTPException)
    detail = str(exc.detail)

    if request.url.path.startswith("/api/"):
        return _problem(exc.status_code, HTTPStatus(exc.status_code).phrase, detail)

    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": detail},
        status_code=exc.status_code,
    )


app = create_app()

__all__ = ["app", "create_app"]
