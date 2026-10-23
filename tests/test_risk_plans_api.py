"""`GET /api/v1/risk-plans` — status, shape and the error seam.

The arithmetic is `test_risk_plan.py`'s; this checks it arrives intact.
"""

from datetime import date

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio

REFERENCE_QUERY = (
    "capital=1600&target_capital=2000&start_date=2026-10-23&end_date=2026-11-25"
    "&weekdays=0&weekdays=1&weekdays=2&weekdays=3&weekdays=4&per_day=4&payout_percent=92"
    "&style=session&risk_percents=0.5&risk_percents=1"
)


async def test_reference_sessions(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/risk-plans?{REFERENCE_QUERY}")

    assert response.status_code == 200
    body = response.json()
    assert (body["trading_days"], body["units"]) == (24, 96)
    assert (body["first_day"], body["last_day"]) == ("2026-10-23", "2026-11-25")
    assert body["daily_growth_percent"] == pytest.approx(0.9341, abs=1e-4)
    assert body["day_one_profit"] == 14.95
    assert len(body["days"]) == 24

    half, one = body["levels"]
    assert (half["wins_needed"], half["wins_needed_best"]) == (110, 108)
    assert half["reachable"] is False
    assert half["band"] == "out_of_reach"
    assert half["balance_if_all_win"] == 1829.99
    assert half["verdict"].startswith("Out of reach at 0.5%")

    assert (one["wins_needed"], one["wins_needed_best"]) == (93, 91)
    assert (one["wins_per_day"], one["per_day"]) == (4, 4)
    assert one["breakeven_percent"] == pytest.approx(78.23, abs=0.01)
    assert one["reachable"] is True
    assert (one["stake"], one["recharge"]) == (5.33, 10.66)
    assert one["verdict"].startswith("Requires winning 93 of 96")


async def test_a_target_below_capital_is_a_problem_naming_the_target(client: AsyncClient) -> None:
    query = REFERENCE_QUERY.replace("target_capital=2000", "target_capital=1000")
    response = await client.get(f"/api/v1/risk-plans?{query}")

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["errors"][0]["field"] == "target_capital"


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (("end_date=2026-11-25", "end_date=2026-10-01"), "end_date"),
        (("payout_percent=92", "payout_percent=50"), "payout_percent"),
        (("risk_percents=1", "risk_percents=0.5"), "risk_percents"),
        (("per_day=4", "per_day=four"), "per_day"),
        (("&weekdays=0&weekdays=1&weekdays=2&weekdays=3&weekdays=4", "&weekdays=9"), "weekdays"),
    ],
)
async def test_refusals_name_their_field(
    client: AsyncClient, change: tuple[str, str], field: str
) -> None:
    response = await client.get(f"/api/v1/risk-plans?{REFERENCE_QUERY.replace(*change)}")

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == field


async def test_a_range_without_the_chosen_weekday_is_refused_as_end_date(
    client: AsyncClient,
) -> None:
    query = "capital=1600&target_capital=2000&weekdays=6&start_date=2026-10-26&end_date=2026-10-30"
    response = await client.get(f"/api/v1/risk-plans?{query}")

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "end_date"


async def test_dates_default_to_today_and_thirty_days_on(client: AsyncClient) -> None:
    response = await client.get("/api/v1/risk-plans?capital=1600&target_capital=2000")

    assert response.status_code == 200
    body = response.json()
    start, end = date.fromisoformat(body["start_date"]), date.fromisoformat(body["end_date"])
    assert (end - start).days == 30
