"""JSON API tests — status codes, response shape, and the error seam.

Not a place to re-test the arithmetic; `test_domain.py` owns that.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Simulation
from tests.conftest import REFERENCE_BODY

pytestmark = pytest.mark.anyio


async def test_health_is_under_the_version_prefix(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_reference_case_round_trips_through_the_api(client: AsyncClient) -> None:
    response = await client.post("/api/v1/simulations", json=REFERENCE_BODY)

    assert response.status_code == 201
    body = response.json()
    assert body["wall_hit"] is True
    assert body["wall_required_stake"] == 910
    assert body["wall_balance_available"] == 163.0
    assert body["losses_survived"] == 8
    assert len(body["entries"]) == 8
    assert [e["label"] for e in body["entries"]] == ["1a", "1b", "2", "3", "4", "5", "6", "7"]


async def test_stored_run_reads_back_identically(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/simulations", json=REFERENCE_BODY)).json()

    fetched = await client.get(f"/api/v1/simulations/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


async def test_unknown_run_is_a_problem_response(client: AsyncClient) -> None:
    response = await client.get("/api/v1/simulations/9999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_impossible_payout_is_rejected_by_the_domain_seam(client: AsyncClient) -> None:
    """A payout above 100% is a domain rejection, not a schema one — 422, not 500."""
    response = await client.post(
        "/api/v1/simulations", json={**REFERENCE_BODY, "payout_ratio": 1.5}
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 422
    assert body["title"] == "Invalid staking configuration"
    assert "payout_ratio" in body["detail"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("capital", -1.0), ("entry_1a", 0.0), ("target_profit", -5.0)],
)
async def test_every_domain_rejection_reaches_the_same_seam(
    client: AsyncClient, field: str, value: float
) -> None:
    response = await client.post("/api/v1/simulations", json={**REFERENCE_BODY, field: value})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_max_entries_above_the_server_ceiling_is_a_schema_rejection(
    client: AsyncClient,
) -> None:
    """This limit protects the server, so it lives in the schema, not the domain."""
    response = await client.post(
        "/api/v1/simulations", json={**REFERENCE_BODY, "max_entries": 10_000}
    )

    assert response.status_code == 422


async def test_delete_is_soft(client: AsyncClient, session: Session) -> None:
    created = (await client.post("/api/v1/simulations", json=REFERENCE_BODY)).json()
    simulation_id = created["id"]

    deleted = await client.delete(f"/api/v1/simulations/{simulation_id}")
    assert deleted.status_code == 204

    listed = await client.get("/api/v1/simulations")
    assert simulation_id not in [row["id"] for row in listed.json()]

    stored = session.scalars(select(Simulation).where(Simulation.id == simulation_id)).one()
    assert stored.deleted_at is not None


async def test_deleting_twice_reports_the_run_as_gone(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/simulations", json=REFERENCE_BODY)).json()

    assert (await client.delete(f"/api/v1/simulations/{created['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/simulations/{created['id']}")).status_code == 404


async def test_listing_returns_newest_first(client: AsyncClient) -> None:
    first = (await client.post("/api/v1/simulations", json=REFERENCE_BODY)).json()
    second = (
        await client.post("/api/v1/simulations", json={**REFERENCE_BODY, "capital": 2000.0})
    ).json()

    listed = (await client.get("/api/v1/simulations")).json()

    assert [row["id"] for row in listed] == [second["id"], first["id"]]
