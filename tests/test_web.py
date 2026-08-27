"""Page tests — the unversioned HTML surface.

These assert that each page renders and that the form behaves, not that the
arithmetic is right; `test_domain.py` owns that.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Simulation
from tests.conftest import REFERENCE_FORM

pytestmark = pytest.mark.anyio


async def test_landing_page_carries_the_theory_and_the_faq(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "Where the plan stops" in body
    assert "<details>" in body  # the FAQ is semantic, not a div with a handler
    # The worked example is produced by the simulator itself.
    assert "910.00" in body
    assert "163.00" in body
    # The opener badge, once per worked example, both identical.
    assert body.count('<div class="badge') == 2
    assert body.count("+$9.20, balance $1009.20") == 2


async def test_simulator_shows_three_primary_inputs_and_a_collapsed_panel(
    client: AsyncClient,
) -> None:
    response = await client.get("/simulator")

    assert response.status_code == 200
    body = response.text
    for field in ("capital", "payout_percent", "target_profit_percent", "entry_1a", "entry_1b"):
        assert f'id="{field}"' in body
    assert 'id="max_entries"' in body  # the one field still under Advanced
    assert '<details class="advanced">' in body  # collapsed: no `open`


async def test_simulator_pre_checks_breakeven_and_double_but_hides_profit_recovery(
    client: AsyncClient,
) -> None:
    """Profit recovery is identical to breakeven at the default $0 target, so
    it shouldn't be offered until a target above $0 makes it distinct."""
    response = await client.get("/simulator")

    body = response.text
    assert 'name="strategies" value="adder_breakeven"' in body
    assert 'name="strategies" value="double"' in body
    assert 'name="strategies" value="adder_profit"' not in body


async def test_submitting_with_no_strategy_checked_is_rejected(client: AsyncClient) -> None:
    """A real browser omits an unchecked checkbox from the POST entirely —
    this reproduces that, not an explicit empty value."""
    form = {k: v for k, v in REFERENCE_FORM.items() if k != "strategies"}
    response = await client.post("/simulator", data=form)

    assert response.status_code == 422
    assert 'id="strategies-error"' in response.text
    assert "Choose at least one strategy." in response.text


async def test_submitting_the_reference_case_redirects_to_its_result(
    client: AsyncClient,
) -> None:
    response = await client.post("/simulator", data=REFERENCE_FORM)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/results/")

    page = await client.get(response.headers["location"])
    assert page.status_code == 200
    assert "910.00" in page.text
    assert "163.00" in page.text
    assert "WALL" in page.text
    # No target set — the badge shows a plain profit, not a pass/fail.
    assert "If both openers win" in page.text
    assert "+$9.20, balance $1009.20" in page.text
    assert "badge--short" not in page.text


async def test_a_target_the_openers_cannot_meet_shows_a_shortfall_badge(
    client: AsyncClient,
) -> None:
    # 1% of $1000 capital is a $10 target.
    response = await client.post(
        "/simulator", data={**REFERENCE_FORM, "target_profit_percent": "1"}
    )
    page = await client.get(response.headers["location"])

    assert "$0.80 short of the $10.00 target" in page.text
    assert 'class="badge badge--short"' in page.text


async def test_suggest_action_fills_in_openers_without_running(client: AsyncClient) -> None:
    """1% of $1000 is a $10 target: ceil(10 / 1.84) = $6 each."""
    response = await client.post(
        "/simulator",
        data={**REFERENCE_FORM, "target_profit_percent": "1", "action": "suggest"},
    )

    assert response.status_code == 200  # re-rendered the form, not a redirect
    body = response.text
    assert 'value="6"' in body
    assert "clears the $10.00 target" in body  # the live preview updates too


async def test_suggest_action_with_no_target_leaves_openers_unchanged(
    client: AsyncClient,
) -> None:
    response = await client.post("/simulator", data={**REFERENCE_FORM, "action": "suggest"})

    assert response.status_code == 200
    assert 'value="5"' in response.text  # REFERENCE_FORM's own entry_1a/1b


async def test_suggested_openers_stay_editable_and_still_run(
    client: AsyncClient, session: Session
) -> None:
    """Suggest, don't seize: the reader can override the filled-in pair and
    the plan still runs with what they actually typed."""
    response = await client.post(
        "/simulator",
        data={**REFERENCE_FORM, "target_profit_percent": "1", "entry_1a": "5", "entry_1b": "5"},
    )

    assert response.status_code == 303
    stored = session.scalars(select(Simulation)).one()
    assert stored.entry_1a == 5.0
    assert stored.entry_1b == 5.0
    assert stored.target_profit == 10.0
    assert stored.target_profit_percent == 1.0


async def test_selecting_one_strategy_behaves_as_a_single_run(client: AsyncClient) -> None:
    """One box checked shouldn't route through the comparison view at all."""
    response = await client.post("/simulator", data={**REFERENCE_FORM, "strategies": ["double"]})

    assert response.status_code == 303
    assert response.headers["location"].startswith("/results/")
    assert "/group/" not in response.headers["location"]


async def test_selecting_two_strategies_redirects_to_a_comparison(
    client: AsyncClient, session: Session
) -> None:
    response = await client.post(
        "/simulator",
        data={**REFERENCE_FORM, "strategies": ["adder_breakeven", "double"]},
    )

    assert response.status_code == 303
    assert "/results/group/" in response.headers["location"]

    page = await client.get(response.headers["location"])
    assert page.status_code == 200
    assert "Breakeven recovery" in page.text
    assert "Double" in page.text
    # Each strategy's own wall, both present on one page.
    assert "910.00" in page.text and "163.00" in page.text
    assert "1620.00" in page.text and "190.00" in page.text
    # The opener badge doesn't vary by strategy — it repeats once per table.
    assert page.text.count('<div class="badge') == 2
    assert page.text.count("+$9.20, balance $1009.20") == 2

    stored = session.scalars(select(Simulation)).all()
    assert len(stored) == 2
    assert stored[0].run_group is not None
    assert stored[0].run_group == stored[1].run_group


async def test_clearing_a_comparison_clears_every_run_in_it(
    client: AsyncClient, session: Session
) -> None:
    created = await client.post(
        "/simulator",
        data={**REFERENCE_FORM, "strategies": ["adder_breakeven", "double"]},
    )
    group_path = created.headers["location"]

    response = await client.post(f"{group_path}/delete")

    assert response.status_code == 303
    assert response.headers["location"] == "/history"
    assert (await client.get(group_path)).status_code == 404

    stored = session.scalars(select(Simulation)).all()
    assert len(stored) == 2
    assert all(s.deleted_at is not None for s in stored)


async def test_a_rejected_plan_keeps_its_values_and_names_the_field(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/simulator", data={**REFERENCE_FORM, "capital": "-50", "target_profit_percent": "7"}
    )

    assert response.status_code == 422
    body = response.text
    assert 'id="capital-error"' in body
    assert 'value="-50"' in body  # the submitted value is preserved
    assert 'value="7"' in body  # ...and so are the ones that were fine


async def test_a_non_numeric_entry_is_reported_on_its_own_field(client: AsyncClient) -> None:
    response = await client.post("/simulator", data={**REFERENCE_FORM, "capital": "lots"})

    assert response.status_code == 422
    assert 'id="capital-error"' in response.text
    assert "Enter a number." in response.text
    # Text that a number input would have silently discarded still comes back.
    assert 'value="lots"' in response.text


async def test_an_impossible_payout_is_reported_in_the_forms_own_units(
    client: AsyncClient,
) -> None:
    response = await client.post("/simulator", data={**REFERENCE_FORM, "payout_percent": "150"})

    assert response.status_code == 422
    assert 'id="payout_percent-error"' in response.text
    assert "no more than 100%" in response.text


async def test_an_advanced_field_error_opens_the_advanced_panel(client: AsyncClient) -> None:
    """max_entries is the one remaining field under Advanced; target_profit_percent
    moved to the primary set in item 4 and no longer exercises this."""
    response = await client.post("/simulator", data={**REFERENCE_FORM, "max_entries": "0"})

    assert response.status_code == 422
    assert '<details class="advanced" open>' in response.text
    assert 'id="max_entries-error"' in response.text


async def test_history_is_empty_before_anything_runs(client: AsyncClient) -> None:
    response = await client.get("/history")

    assert response.status_code == 200
    assert "Nothing stored yet" in response.text


async def test_history_lists_a_run_and_clearing_retains_it(
    client: AsyncClient, session: Session
) -> None:
    await client.post("/simulator", data=REFERENCE_FORM)

    listed = await client.get("/history")
    assert "#1" in listed.text

    cleared = await client.post("/history/clear")
    assert cleared.status_code == 303

    after = await client.get("/history")
    assert "Nothing stored yet" in after.text

    # Cleared, not dropped.
    stored = session.scalars(select(Simulation)).all()
    assert len(stored) == 1
    assert stored[0].deleted_at is not None


async def test_clearing_one_run_returns_to_history(client: AsyncClient, session: Session) -> None:
    created = await client.post("/simulator", data=REFERENCE_FORM)
    path = created.headers["location"]

    response = await client.post(f"{path}/delete")

    assert response.status_code == 303
    assert response.headers["location"] == "/history"
    assert (await client.get(path)).status_code == 404
    assert session.scalars(select(Simulation)).one().deleted_at is not None


async def test_history_shows_the_strategy_and_links_a_comparison_to_its_group(
    client: AsyncClient,
) -> None:
    await client.post(
        "/simulator",
        data={**REFERENCE_FORM, "strategies": ["adder_breakeven", "double"]},
    )

    listed = await client.get("/history")

    assert "Breakeven recovery" in listed.text
    assert "Double" in listed.text
    assert '<th scope="col">Strategy</th>' in listed.text
    assert "/results/group/" in listed.text


async def test_history_shows_the_target_as_a_percentage_when_that_is_what_was_typed(
    client: AsyncClient,
) -> None:
    await client.post("/simulator", data={**REFERENCE_FORM, "target_profit_percent": "1"})

    listed = await client.get("/history")

    assert '<th scope="col" class="num">Target</th>' in listed.text
    assert "1%" in listed.text


async def test_a_missing_run_renders_a_page_not_a_json_body(client: AsyncClient) -> None:
    response = await client.get("/results/9999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


async def test_the_current_page_is_marked_in_the_nav(client: AsyncClient) -> None:
    response = await client.get("/simulator")

    assert 'href="/simulator" aria-current="page"' in response.text
