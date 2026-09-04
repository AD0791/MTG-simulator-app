"""Structured logging: one configuration, one format, stdout only.

Named `log`, not `logging`, so no module in this package has to reason about
which one a bare `import logging` reaches.

Everything the application logs goes through structlog, and everything *else*
logs — uvicorn, SQLAlchemy, Alembic — is rendered by the same formatter, so the
stream a platform collects is one shape from the first line to the last.

The layer that logs nothing is `domain/`. It imports no framework, no ORM and no
third-party library at all, which is what keeps the simulation runnable under a
bare `python3`. A logger there would be the convenient import that ends it.
"""

import logging
import sys
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

import structlog
from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.engine import make_url
from starlette.middleware.base import RequestResponseEndpoint
from structlog.typing import Processor

from .config import Settings

# Applied to our own events and, as `foreign_pre_chain`, to records from
# libraries that log through the standard library. Both routes therefore produce
# the same keys.
_SHARED: Sequence[Processor] = (
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
)


def _renderer(log_json: bool) -> Sequence[Processor]:
    """The last processors in the chain, which differ by output format.

    `ConsoleRenderer` formats a traceback itself; `JSONRenderer` cannot, and
    needs `format_exc_info` to have already flattened it into a string. So the
    exception processor belongs here rather than in the shared chain, where it
    would strip the console renderer's own handling.
    """
    if log_json:
        return (structlog.processors.format_exc_info, structlog.processors.JSONRenderer())
    return (structlog.dev.ConsoleRenderer(),)


def configure(settings: Settings) -> None:
    """Point every logger in the process at one stdout handler.

    Called from `create_app`, before the application is assembled — anything
    logged during assembly should already be formatted.
    """
    structlog.configure(
        processors=[*_SHARED, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Deliberately off. A cached bound logger keeps the processor chain it
        # was built with, and `structlog.testing.capture_logs` then intercepts
        # nothing — tests/test_logging.py would assert against an empty list.
        # The caching win is meaningless at this traffic; the test seam is not.
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=list(_SHARED),
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *_renderer(settings.log_json),
            ],
        )
    )

    # Logs go to stdout and the platform collects them. No files, no rotation —
    # a file handler in a container loses its data on restart.
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    # Uvicorn installs its own handlers with `propagate: False` when it starts,
    # which is before it imports the application and therefore before this
    # runs. Left alone, its startup lines bypass the root handler entirely and
    # the deployed stream is JSON with four lines of prose in the middle of it.
    # Clearing the handlers and restoring propagation sends them here instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.asgi"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # `log_requests` records the same fact with a request id attached, so
    # uvicorn's access line would be a second, poorer copy of every request.
    logging.getLogger("uvicorn.access").disabled = True


def describe_database(url: str) -> str:
    """Which database was actually opened, with any password masked.

    The scheme alone is not enough, and this was proven the expensive way:
    `sqlite:///./app.db` resolves against the working directory, and SQLite
    creates an empty file rather than reporting a missing one. Started from the
    wrong directory the app serves `/` and `/simulator` at 200 and fails only on
    `/history`, while the real database sits untouched in the repository root.

    Resolving the path is what turns that debugging session into one glance at
    the first line of the log. A server URL is rendered instead with its
    password replaced — the host and database name are the diagnostic part, and
    the credential must never reach a log platform.
    """
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite") and parsed.database:
        return f"sqlite:///{Path(parsed.database).resolve()}"
    return parsed.render_as_string(hide_password=True)


logger = structlog.stdlib.get_logger()


async def log_requests(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """One line per request, and the context every later line inherits.

    Binding the request id here is what lets a service or an error handler log
    without being handed anything: `merge_contextvars` puts these keys on every
    event raised while the request is in flight. Nothing downstream grows a
    parameter to carry them.
    """
    # Assets say nothing a request id would help with, and there are many.
    if request.url.path.startswith("/static"):
        return await call_next(request)

    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Logged, then re-raised untouched: Starlette still owns the 500. This
        # is the one place an unhandled failure is recorded with its request id.
        logger.exception("http_request_failed", duration_ms=_elapsed_ms(started))
        raise

    logger.info("http_request", status=response.status_code, duration_ms=_elapsed_ms(started))

    # So a reader looking at a failed page can quote the id back.
    response.headers["x-request-id"] = request_id
    return response


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
