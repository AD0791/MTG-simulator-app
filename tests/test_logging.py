"""Logging tests — the request context, and the events worth keeping.

Not a place to assert on formatting. `capture_logs` intercepts events before any
renderer runs, so what these pin is which events fire and which keys they carry.
"""

from collections.abc import Generator
from contextlib import contextmanager

import pytest
import structlog
from httpx import AsyncClient
from structlog.typing import EventDict

from app.log import describe_database
from tests.conftest import REFERENCE_BODY, REFERENCE_FORM

pytestmark = pytest.mark.anyio


def test_a_sqlite_database_is_described_by_its_resolved_path() -> None:
    """The scheme alone can't tell the real database from an empty one created
    by starting in the wrong directory — the absolute path can."""
    described = describe_database("sqlite:///./app.db")

    assert described.startswith("sqlite:////")
    assert described.endswith("/app.db")
    assert "./" not in described


def test_a_server_password_never_reaches_the_log() -> None:
    described = describe_database("postgresql+psycopg://user:hunter2@db.example:5432/mtg")

    assert "hunter2" not in described
    assert "db.example:5432/mtg" in described


@contextmanager
def capture() -> Generator[list[EventDict]]:
    """`capture_logs`, with `merge_contextvars` put back.

    The stock helper disables every configured processor for its duration,
    which includes the one that merges the middleware's bound request context.
    Without this the request id — the whole point of the context — is invisible
    to a test while working perfectly in production.
    """
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as captured:
        yield captured


def _events(captured: list[EventDict], name: str) -> list[EventDict]:
    return [entry for entry in captured if entry["event"] == name]


def _one(captured: list[EventDict], name: str) -> EventDict:
    matched = _events(captured, name)
    assert len(matched) == 1, f"expected exactly one {name}, got {len(matched)}"
    return matched[0]


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.headers["x-request-id"]


async def test_an_incoming_request_id_is_kept_rather_than_replaced(client: AsyncClient) -> None:
    """A proxy's trace id has to survive into the app, or the two log streams
    can't be joined."""
    with capture() as captured:
        response = await client.get("/api/v1/health", headers={"X-Request-ID": "trace-me"})

    assert response.headers["x-request-id"] == "trace-me"
    assert _one(captured, "http_request")["request_id"] == "trace-me"


async def test_the_request_line_records_the_route_and_its_status(client: AsyncClient) -> None:
    with capture() as captured:
        await client.get("/api/v1/simulations/9999")

    request = _one(captured, "http_request")
    assert request["method"] == "GET"
    assert request["path"] == "/api/v1/simulations/9999"
    assert request["status"] == 404
    assert isinstance(request["duration_ms"], float)

    # The 404 is raised as an HTTPException, so the error seam records it too.
    assert _one(captured, "http_error")["status"] == 404


async def test_a_stored_run_logs_its_wall(client: AsyncClient) -> None:
    """The canonical reference case, so this pins real numbers rather than the
    mere presence of a key."""
    with capture() as captured:
        await client.post("/api/v1/simulations", json=REFERENCE_BODY)

    stored = _one(captured, "simulation.stored")
    # The JSON body names no strategy, so the schema default stands. At this
    # body's $0 target it produces the same ladder breakeven would.
    assert stored["strategy"] == "adder_profit"
    assert stored["capital"] == 1000.0
    assert stored["wall_hit"] is True
    assert stored["wall_required_stake"] == 910
    assert stored["losses_survived"] == 8

    # The middleware bound the context, so the service's own event carries the
    # request id without having been handed it.
    assert stored["request_id"] == _one(captured, "http_request")["request_id"]


async def test_a_rejected_plan_is_logged_at_the_error_seam(client: AsyncClient) -> None:
    with capture() as captured:
        await client.post("/api/v1/simulations", json={**REFERENCE_BODY, "capital": -1})

    rejected = _one(captured, "plan.rejected")
    assert rejected["log_level"] == "warning"
    assert "capital" in rejected["detail"]


async def test_a_rejected_form_names_its_offending_field(client: AsyncClient) -> None:
    form = {**REFERENCE_FORM, "capital": "not a number"}

    with capture() as captured:
        await client.post("/simulator", data=form)

    rejected = _one(captured, "form.rejected")
    assert rejected["stage"] == "shape"
    assert rejected["fields"] == ["capital"]


async def test_the_form_records_a_domain_rejection_the_error_seam_never_sees(
    client: AsyncClient,
) -> None:
    """The page catches the domain's ValueError to re-render the field, so
    `plan.rejected` cannot fire. Without `form.rejected` this would go
    unrecorded entirely."""
    form = {**REFERENCE_FORM, "entry_1a": "0"}

    with capture() as captured:
        await client.post("/simulator", data=form)

    rejected = _one(captured, "form.rejected")
    assert rejected["stage"] == "plan"
    assert rejected["fields"] == ["entry_1a"]
    assert not _events(captured, "plan.rejected")


async def test_a_comparison_is_logged_as_one_group(client: AsyncClient) -> None:
    form = {**REFERENCE_FORM, "strategies": ["adder_breakeven", "double"]}

    with capture() as captured:
        await client.post("/simulator", data=form)

    group = _one(captured, "simulation.group_stored")
    assert group["count"] == 2
    assert group["strategies"] == ["adder_breakeven", "double"]
    # The reference case: doubling reaches the wall two entries sooner.
    assert group["losses_survived"] == [8, 6]
    assert group["run_group"] is not None


async def test_clearing_a_run_is_recorded(client: AsyncClient) -> None:
    """A soft delete leaves the row in place, so the log line is the only
    trace that someone cleared it."""
    created = await client.post("/api/v1/simulations", json=REFERENCE_BODY)
    simulation_id = created.json()["id"]

    with capture() as captured:
        await client.delete(f"/api/v1/simulations/{simulation_id}")

    cleared = _one(captured, "simulation.cleared")
    assert cleared["scope"] == "one"
    assert cleared["simulation_id"] == simulation_id
    assert cleared["count"] == 1


async def test_static_assets_are_not_logged(client: AsyncClient) -> None:
    """Asset requests say nothing a request id would help with, and there are
    many of them per page."""
    with capture() as captured:
        response = await client.get("/static/css/app.css")

    assert response.status_code == 200
    assert not _events(captured, "http_request")
