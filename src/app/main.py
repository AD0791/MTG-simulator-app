"""Application assembly: routers, static files, and the error seam."""

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from . import log
from .api import v1
from .config import get_settings
from .domain.staking_simulator import InvalidStakingConfig
from .web import router as web_router
from .web.templates import STATIC_DIR, templates

PROBLEM_JSON = "application/problem+json"

logger = log.logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    # `database` is the resolved path, not the configured URL — it answers "am I
    # running from the wrong directory against an empty SQLite file", which the
    # scheme alone cannot. Any password is masked; see `log.describe_database`.
    logger.info(
        "app.started",
        app_name=settings.app_name,
        log_level=settings.log_level,
        database=log.describe_database(settings.database_url),
    )
    yield
    logger.info("app.stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    # Before the app is assembled, so anything logged during assembly is
    # already formatted.
    log.configure(settings)

    app = FastAPI(
        title=settings.app_name,
        summary="Locates the entry at which a staking plan can no longer fund its next stake.",
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.middleware("http")(log.log_requests)

    # JSON is versioned; pages are not.
    app.include_router(v1.router)
    app.include_router(web_router)

    app.add_exception_handler(ValueError, _invalid_configuration)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    # Starlette's class, which FastAPI's subclasses: an unknown path or a wrong
    # method is raised by the router before any route runs, and registering the
    # subclass alone lets those escape as plain JSON.
    app.add_exception_handler(HTTPException, _http_error)
    return app


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def _problem(
    status: int,
    title: str,
    detail: str,
    errors: Sequence[Mapping[str, str]] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "errors": list(errors),
        },
        media_type=PROBLEM_JSON,
        headers=headers,
    )


async def _invalid_configuration(request: Request, exc: Exception) -> Response:
    """The one translation of a domain rejection into an HTTP response.

    `StakingConfig.__post_init__` is the authoritative validator for a staking
    plan. Nothing re-implements its rules, and no route wraps the simulator in a
    `try/except` to reach this — the exception arrives here on its own. The
    domain names the field it refused; any other `ValueError` (a Pydantic error
    raised inside a route is one) names none.
    """
    logger.warning("plan.rejected", detail=str(exc))
    errors = (
        [{"field": exc.field, "detail": str(exc)}] if isinstance(exc, InvalidStakingConfig) else []
    )
    return _problem(422, "Invalid staking configuration", str(exc), errors)


async def _invalid_request(request: Request, exc: Exception) -> Response:
    """Problem+json for a malformed API request, FastAPI's default elsewhere.

    The same shape as a domain rejection, so a client reads one error format
    whichever layer refused the request.
    """
    assert isinstance(exc, RequestValidationError)
    if not _is_api(request):
        return await request_validation_exception_handler(request, exc)

    errors = [
        {"field": _request_field(error["loc"]), "detail": str(error["msg"])}
        for error in exc.errors()
    ]
    # Field names, never the submitted values.
    logger.warning("request.rejected", fields=sorted({error["field"] for error in errors}))
    return _problem(422, "Invalid request", "The request does not match the API contract.", errors)


def _request_field(loc: Sequence[object]) -> str:
    """`("body", "capital")` → `capital`; a location with no field → its source."""
    return str(loc[1]) if len(loc) > 1 else str(loc[0])


async def _http_error(request: Request, exc: Exception) -> Response:
    """Problem+json for the JSON API, a rendered page for the browser."""
    assert isinstance(exc, HTTPException)
    detail = str(exc.detail)
    logger.warning("http_error", status=exc.status_code, detail=detail)

    if _is_api(request):
        return _problem(
            exc.status_code, HTTPStatus(exc.status_code).phrase, detail, headers=exc.headers
        )

    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


app = create_app()

__all__ = ["app", "create_app"]
