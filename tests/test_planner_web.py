"""The `/planner` page — a GET form whose address holds the plan — and the
form state both pages keep between visits."""

import re

import pytest
from httpx import AsyncClient

from tests.conftest import REFERENCE_FORM

pytestmark = pytest.mark.anyio

REFERENCE_QUERY = (
    "capital=1600&target_capital=2000&start_date=2026-10-23&end_date=2026-11-25"
    "&weekdays=0&weekdays=1&weekdays=2&weekdays=3&weekdays=4&per_day=4&payout_percent=92"
    "&style=session&risk_1=0.5&risk_2=1"
)


def _value(page: str, name: str) -> str | None:
    match = re.search(rf'id="{name}"\s+name="{name}"[^>]*?value="([^"]*)"', page, re.S)
    return match.group(1) if match else None


async def test_the_bare_page_shows_the_defaults_and_no_results(client: AsyncClient) -> None:
    page = await client.get("/planner")

    assert page.status_code == 200
    assert _value(page.text, "capital") == "1600"
    assert _value(page.text, "target_capital") == "2000"
    assert _value(page.text, "risk_1") == "0.25"
    assert "What the target requires" not in page.text
    assert 'href="/planner" aria-current="page"' in page.text


async def test_the_reference_sessions_render(client: AsyncClient) -> None:
    page = await client.get(f"/planner?{REFERENCE_QUERY}")

    assert page.status_code == 200
    assert "0.93%" in page.text
    assert "Out of reach" in page.text
    assert "93" in page.text
    assert "91&ndash;93 of 96" in page.text
    assert "$5.33 + $10.66" in page.text
    assert page.text.count('<li class="level level--') == 2
    # 24 days is under a month, so the schedule starts open.
    assert '<details class="schedule-reveal" open>' in page.text
    assert page.text.count('<th scope="row" class="entry">') == 24
    assert "visually-hidden" in page.text.split('class="formulas"')[1]


async def test_a_bad_target_is_refused_beside_its_input(client: AsyncClient) -> None:
    query = REFERENCE_QUERY.replace("target_capital=2000", "target_capital=1000")
    page = await client.get(f"/planner?{query}")

    assert page.status_code == 422
    assert 'id="target_capital-error"' in page.text
    assert "The target must be more than your capital." in page.text
    assert _value(page.text, "target_capital") == "1000"
    assert _value(page.text, "capital") == "1600"
    assert "planner_form" not in page.headers.get("set-cookie", "")


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (("risk_2=1", "risk_2=0.5"), "risk_2"),
        (("risk_2=1", "risk_2=100"), "risk_2"),
        (("risk_1=0.5", "risk_1=0"), "risk_1"),
        (("risk_2=1", "risk_2=&risk_3=1&risk_4=1"), "risk_4"),
        (("risk_1=0.5", "risk_1="), "risk_1"),
        (("payout_percent=92", "payout_percent=50"), "payout_percent"),
        (("payout_percent=92", "payout_percent=101"), "payout_percent"),
        (("end_date=2026-11-25", "end_date=2026-10-01"), "end_date"),
        (("per_day=4", "per_day=four"), "per_day"),
        (("&weekdays=0&weekdays=1&weekdays=2&weekdays=3&weekdays=4", ""), "weekdays"),
    ],
)
async def test_each_refusal_points_at_its_own_input(
    client: AsyncClient, change: tuple[str, str], field: str
) -> None:
    page = await client.get(f"/planner?{REFERENCE_QUERY.replace(*change)}")

    assert page.status_code == 422
    assert f'id="{field}-error"' in page.text


async def test_the_last_plan_comes_back_on_a_bare_visit(client: AsyncClient) -> None:
    first = await client.get(f"/planner?{REFERENCE_QUERY}")
    assert "planner_form=" in first.headers["set-cookie"]

    again = await client.get("/planner")
    assert again.status_code == 200
    assert "Out of reach at 0.5%" in again.text
    assert _value(again.text, "risk_2") == "1"


async def test_reset_shows_the_defaults_and_forgets_the_plan(client: AsyncClient) -> None:
    await client.get(f"/planner?{REFERENCE_QUERY}")
    reset = await client.get("/planner?reset=1")

    assert reset.status_code == 200
    assert "What the target requires" not in reset.text
    assert _value(reset.text, "risk_1") == "0.25"
    assert 'planner_form=""' in reset.headers["set-cookie"]
    assert "What the target requires" not in (await client.get("/planner")).text


async def test_a_saved_plan_that_no_longer_validates_falls_back_to_the_defaults(
    client: AsyncClient,
) -> None:
    client.cookies.set("planner_form", "capital=1600&target_capital=10")
    page = await client.get("/planner")

    assert page.status_code == 200
    assert _value(page.text, "target_capital") == "2000"


async def test_the_simulator_remembers_its_last_submission(client: AsyncClient) -> None:
    created = await client.post("/simulator", data={**REFERENCE_FORM, "capital": "1234"})
    assert created.status_code == 303
    assert "simulator_form=" in created.headers["set-cookie"]

    page = await client.get("/simulator")
    assert _value(page.text, "capital") == "1234"

    run_id = created.headers["location"].rsplit("/", 1)[1]
    client.cookies.clear()
    from_run = await client.get(f"/simulator?from={run_id}")
    assert _value(from_run.text, "capital") == "1234"
    assert _value(from_run.text, "payout_percent") == "92"
    assert _value(from_run.text, "risk_percent") == "0.5"


async def test_a_comparison_prefills_every_strategy(client: AsyncClient) -> None:
    created = await client.post(
        "/simulator", data={**REFERENCE_FORM, "strategies": ["adder_breakeven", "double"]}
    )
    group = created.headers["location"].rsplit("/", 1)[1]
    client.cookies.clear()

    page = await client.get(f"/simulator?group={group}")
    assert page.text.count("checked") >= 3  # two strategies plus the opener radio


@pytest.mark.parametrize(
    "query", ["?from=999999", "?from=abc", "?group=not-a-uuid", f"?group={'0' * 32}"]
)
async def test_a_missing_run_falls_through_to_the_defaults(client: AsyncClient, query: str) -> None:
    page = await client.get(f"/simulator{query}")

    assert page.status_code == 200
    assert _value(page.text, "capital") == "1000"


async def test_a_garbage_cookie_does_not_break_the_simulator(client: AsyncClient) -> None:
    client.cookies.set("simulator_form", "%%%&&&==;;garbage")
    page = await client.get("/simulator")

    assert page.status_code == 200


async def test_results_offer_to_change_their_inputs(client: AsyncClient) -> None:
    created = await client.post("/simulator", data=REFERENCE_FORM)
    run_id = created.headers["location"].rsplit("/", 1)[1]
    page = await client.get(created.headers["location"])

    assert f'href="/simulator?from={run_id}">Change these inputs</a>' in page.text
    assert 'href="/simulator">New run</a>' in page.text
