"""JSON API tests — status codes, response shape, and the error seam.

Not a place to re-test the arithmetic; `test_domain.py` owns that.
"""

import uuid

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


async def test_explicit_null_entry_1b_produces_a_single_opener_run(client: AsyncClient) -> None:
    body = {**REFERENCE_BODY, "entry_1b": None}
    response = await client.post("/api/v1/simulations", json=body)

    assert response.status_code == 201
    result = response.json()
    assert result["wall_required_stake"] == 1002
    assert result["wall_balance_available"] == 79.0
    assert result["losses_survived"] == 8
    assert result["entry_1b"] is None
    assert [e["label"] for e in result["entries"]][:2] == ["1", "2"]


async def test_omitting_entry_1b_still_produces_the_two_opener_reference_case(
    client: AsyncClient,
) -> None:
    """The regression proving the contract didn't shift: a caller who never
    knew about `opener_count` keeps getting exactly what they always got."""
    body = {k: v for k, v in REFERENCE_BODY.items() if k != "entry_1b"}
    response = await client.post("/api/v1/simulations", json=body)

    assert response.status_code == 201
    result = response.json()
    assert result["wall_required_stake"] == 910
    assert result["wall_balance_available"] == 163.0
    assert result["losses_survived"] == 8
    assert [e["label"] for e in result["entries"]][:2] == ["1a", "1b"]


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


async def test_clearing_every_run_is_soft(client: AsyncClient, session: Session) -> None:
    await client.post("/api/v1/simulations", json=REFERENCE_BODY)
    await client.post("/api/v1/simulations", json=REFERENCE_BODY)

    assert (await client.delete("/api/v1/simulations")).status_code == 204
    assert (await client.get("/api/v1/simulations")).json() == []

    stored = session.scalars(select(Simulation)).all()
    assert len(stored) == 2
    assert all(simulation.deleted_at is not None for simulation in stored)


# --- The view model: bands, wall share, badge, target ------------------------


async def test_a_stored_run_arrives_with_both_ramps_classified(client: AsyncClient) -> None:
    """The bands come from the server, so no client restates a threshold."""
    body = (await client.post("/api/v1/simulations", json=REFERENCE_BODY)).json()
    first, last = body["entries"][0], body["entries"][-1]

    assert (first["position"], first["band"], first["drawdown_band"]) == (1, "calm", None)
    assert (last["band"], last["drawdown_band"]) == ("danger", "critical")
    assert last["drawdown"] == pytest.approx(0.837)
    assert body["wall_share"] == pytest.approx(910 / 163)


async def test_a_stored_run_arrives_with_its_opener_badge(client: AsyncClient) -> None:
    body = (await client.post("/api/v1/simulations", json=REFERENCE_BODY)).json()

    assert body["opener_badge"] == {
        "profit": 9.2,
        "balance": 1009.2,
        "target": None,
        "meets_target": None,
        "opener_count": 2,
    }


async def test_the_listing_carries_the_target(client: AsyncClient) -> None:
    await client.post("/api/v1/simulations", json={**REFERENCE_BODY, "target_profit": 50.0})

    [row] = (await client.get("/api/v1/simulations")).json()

    assert row["target_profit"] == 50.0
    assert row["target_profit_percent"] is None


async def test_strategies_are_listed_in_form_order_with_their_labels(client: AsyncClient) -> None:
    response = await client.get("/api/v1/strategies")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "adder_breakeven", "label": "Breakeven recovery"},
        {"name": "adder_profit", "label": "Profit recovery"},
        {"name": "double", "label": "Double"},
    ]


# --- Ladders: simulated, never stored ----------------------------------------


async def test_a_ladder_is_simulated_without_being_stored(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ladders", params={**REFERENCE_BODY, "strategy": "double"})

    assert response.status_code == 200
    body = response.json()
    assert body["wall_required_stake"] == 1620
    assert body["wall_balance_available"] == 190.0
    assert body["losses_survived"] == 6
    assert [entry["position"] for entry in body["entries"]] == [1, 2, 3, 4, 5, 6]
    assert (await client.get("/api/v1/simulations")).json() == []


async def test_an_impossible_ladder_names_the_field_the_domain_refused(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/ladders", params={**REFERENCE_BODY, "payout_ratio": 1.5})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert [error["field"] for error in response.json()["errors"]] == ["payout_ratio"]


# --- Openers: the badge and the suggestion -----------------------------------


async def test_the_opener_badge_reads_the_reference_case(client: AsyncClient) -> None:
    params = {"capital": 1000, "entry_1a": 5, "entry_1b": 5, "payout_ratio": 0.92}

    response = await client.get("/api/v1/openers/badge", params=params)

    assert response.status_code == 200
    assert response.json() == {
        "profit": 9.2,
        "balance": 1009.2,
        "target": None,
        "meets_target": None,
        "opener_count": 2,
    }


async def test_the_opener_badge_resolves_a_percentage_target(client: AsyncClient) -> None:
    """One opener of $28 returns $25.76 — short of 5% of $1000."""
    params = {"capital": 1000, "entry_1a": 28, "payout_ratio": 0.92, "target_profit_percent": 5}

    body = (await client.get("/api/v1/openers/badge", params=params)).json()

    assert (body["opener_count"], body["target"], body["meets_target"]) == (1, 50.0, False)


async def test_a_suggested_opener_shows_its_working(client: AsyncClient) -> None:
    params = {"capital": 1000, "payout_ratio": 0.92, "target_profit_percent": 5}

    derivation = (await client.get("/api/v1/openers/suggestion", params=params)).json()[
        "derivation"
    ]

    assert derivation["opener"] == 28
    assert derivation["divisor"] == pytest.approx(1.84)
    assert (derivation["returns"], derivation["surplus"]) == (51.52, 1.52)


async def test_no_opener_is_suggested_without_a_target(client: AsyncClient) -> None:
    params = {"capital": 1000, "payout_ratio": 0.92}

    response = await client.get("/api/v1/openers/suggestion", params=params)

    assert response.json() == {"derivation": None}


@pytest.mark.parametrize("payout_ratio", [0, 1.5])
async def test_an_impossible_payout_suggestion_is_refused_by_the_domain_rule(
    client: AsyncClient, payout_ratio: float
) -> None:
    """Zero would divide by zero; above 1 would size openers for an impossible plan."""
    params = {"capital": 1000, "payout_ratio": payout_ratio, "target_profit_percent": 5}

    response = await client.get("/api/v1/openers/suggestion", params=params)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert [error["field"] for error in response.json()["errors"]] == ["payout_ratio"]


# --- Run groups: one plan, several strategies --------------------------------

GROUP_BODY = {
    "capital": 1000.0,
    "entry_1a": 5.0,
    "entry_1b": 5.0,
    "payout_ratio": 0.92,
    "target_profit_percent": 5.0,
    "strategies": ["adder_breakeven", "adder_profit", "double"],
}


async def test_a_run_group_stores_every_strategy_under_one_id(client: AsyncClient) -> None:
    response = await client.post("/api/v1/run-groups", json=GROUP_BODY)

    assert response.status_code == 201
    body = response.json()
    assert body["run_group"] is not None
    assert [run["strategy"] for run in body["simulations"]] == GROUP_BODY["strategies"]
    assert {run["run_group"] for run in body["simulations"]} == {body["run_group"]}
    assert {
        (run["target_profit"], run["target_profit_percent"]) for run in body["simulations"]
    } == {(50.0, 5.0)}


async def test_a_single_strategy_group_has_nothing_to_compare(client: AsyncClient) -> None:
    body = (
        await client.post("/api/v1/run-groups", json={**GROUP_BODY, "strategies": ["double"]})
    ).json()

    assert body["run_group"] is None
    assert len(body["simulations"]) == 1


async def test_a_run_group_reads_back_in_submission_order(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/run-groups", json=GROUP_BODY)).json()

    fetched = await client.get(f"/api/v1/run-groups/{created['run_group']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


async def test_an_unknown_run_group_is_a_problem_response(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/run-groups/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_clearing_a_run_group_is_soft_and_it_is_gone_afterwards(
    client: AsyncClient, session: Session
) -> None:
    created = (await client.post("/api/v1/run-groups", json=GROUP_BODY)).json()
    path = f"/api/v1/run-groups/{created['run_group']}"

    assert (await client.delete(path)).status_code == 204
    assert (await client.get(path)).status_code == 404
    assert (await client.delete(path)).status_code == 404

    stored = session.scalars(
        select(Simulation).where(Simulation.run_group == uuid.UUID(created["run_group"]))
    ).all()
    assert len(stored) == 3
    assert all(simulation.deleted_at is not None for simulation in stored)


async def test_a_rejected_run_group_stores_nothing(client: AsyncClient) -> None:
    response = await client.post("/api/v1/run-groups", json={**GROUP_BODY, "payout_ratio": 1.5})

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["payout_ratio"]
    assert (await client.get("/api/v1/simulations")).json() == []


async def test_a_run_group_needs_at_least_one_strategy(client: AsyncClient) -> None:
    response = await client.post("/api/v1/run-groups", json={**GROUP_BODY, "strategies": []})

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["strategies"]


# --- One error shape under /api/ ---------------------------------------------


async def test_a_malformed_request_is_a_problem_naming_its_field(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/simulations", json={**REFERENCE_BODY, "max_entries": 10_000}
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "Invalid request"
    assert [error["field"] for error in body["errors"]] == ["max_entries"]


async def test_a_domain_rejection_names_the_entry_it_refused(client: AsyncClient) -> None:
    response = await client.post("/api/v1/simulations", json={**REFERENCE_BODY, "entry_1b": 0.0})

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["entry_1b"]


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [("GET", "/api/v1/nowhere", 404), ("PUT", "/api/v1/simulations", 405)],
)
async def test_routing_failures_under_the_api_are_problems_too(
    client: AsyncClient, method: str, path: str, status: int
) -> None:
    response = await client.request(method, path)

    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
