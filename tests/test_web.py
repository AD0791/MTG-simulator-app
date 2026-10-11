"""Page tests — the unversioned HTML surface.

These assert that each page renders and that the form behaves, not that the
arithmetic is right; `test_domain.py` owns that.
"""

import os
import re

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
    for field in ("capital", "payout_percent", "risk_percent"):
        assert f'id="{field}"' in body
    # Nobody types an opener or a target any more.
    for gone in ("entry_1a", "entry_1b", "target_profit_percent"):
        assert f'id="{gone}"' not in body
    assert 'id="max_entries"' in body  # the one field still under Advanced
    assert '<details class="advanced">' in body  # collapsed: no `open`


async def test_simulator_offers_breakeven_and_double_only(client: AsyncClient) -> None:
    """Profit recovery went with target profit."""
    response = await client.get("/simulator")

    body = response.text
    assert 'name="strategies" value="adder_breakeven"' in body
    assert 'name="strategies" value="double"' in body
    assert 'name="strategies" value="adder_profit"' not in body


async def test_simulator_shows_the_opener_radio_defaulting_to_two(client: AsyncClient) -> None:
    response = await client.get("/simulator")

    body = response.text
    assert 'name="opener_count" value="2"' in body
    assert 'name="opener_count" value="1"' in body
    assert 'name="opener_count" value="2" checked' in body


async def test_a_one_entry_submission_runs_and_renders(client: AsyncClient) -> None:
    response = await client.post("/simulator", data={**REFERENCE_FORM, "opener_count": "1"})

    assert response.status_code == 303
    page = await client.get(response.headers["location"])
    assert page.status_code == 200
    assert "1002.00" in page.text
    assert "79.00" in page.text
    assert "If the opener wins" in page.text


async def test_the_form_previews_the_opening_entry_it_will_place(client: AsyncClient) -> None:
    """The user's own example, rendered: 0.25% of $3534.68 is $8.84."""
    form = {**REFERENCE_FORM, "capital": "3534.68", "risk_percent": "0.25", "payout_percent": "x"}
    response = await client.post("/simulator", data=form)  # rejected, so it re-renders

    assert response.status_code == 422
    assert "$3,534.68 &times; 0.25 &divide; 100 = $8.84" in response.text
    assert "on each of the two openers" in response.text


@pytest.mark.parametrize(("opener_count", "entry_1b"), [("2", 8.84), ("1", None)])
async def test_the_stored_openers_are_the_risk_share_of_capital(
    client: AsyncClient, session: Session, opener_count: str, entry_1b: float | None
) -> None:
    """Each opener is capital x risk / 100 rounded to the cent, and nothing else."""
    response = await client.post(
        "/simulator",
        data={
            **REFERENCE_FORM,
            "capital": "3534.68",
            "risk_percent": "0.25",
            "opener_count": opener_count,
        },
    )

    assert response.status_code == 303
    stored = session.scalars(select(Simulation)).one()
    assert (stored.entry_1a, stored.entry_1b, stored.risk_percent) == (8.84, entry_1b, 0.25)


@pytest.mark.parametrize("risk_percent", ["0", "-1", "0.0001"])
async def test_a_risk_that_sizes_no_entry_is_reported_on_the_risk_field(
    client: AsyncClient, risk_percent: str
) -> None:
    response = await client.post(
        "/simulator", data={**REFERENCE_FORM, "risk_percent": risk_percent}
    )

    assert response.status_code == 422
    assert 'id="risk_percent-error"' in response.text
    assert "Risk must be above 0%" in response.text
    assert "Enter a capital and a risk above 0% to size the opening entry." in response.text


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
    assert "If both openers win" in page.text
    assert "+$9.20, balance $1009.20" in page.text
    assert "0.5% of capital per entry" in page.text
    # Entry 7's balance cell is 83.7% drawdown — critical band, not a wall row.
    assert 'class="num balance-cell drawdown-critical"' in page.text
    assert "needs +513%" in page.text
    # The first several rows stay uncoloured — this fixture never spends most
    # of the table, per the roadmap's own "calm until abruptly it isn't."
    assert page.text.count("balance-cell drawdown-") == 1
    # Below the ladder: what to keep in the account. Eight losses need $837; a
    # ninth would take $837 + $910 = $1,747, $747 over capital -- the wall, and
    # the table's last row.
    assert "How much to keep in the account" in page.text
    assert "837.00" in page.text and "1747.00" in page.text
    assert "over capital by 747.00" in page.text
    assert page.text.count('class="funding-wall"') == 1
    assert page.text.count("over capital by") == 1


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
    assert "640.00" in page.text and "370.00" in page.text
    # Only doubling falls short of a full recovery, so only its table marks it.
    assert page.text.count("win-short") == 2
    assert "short $2.80" in page.text and "short $15.60" in page.text
    assert page.text.count("If won &mdash; short recovery") == 1
    # Each strategy carries its own funding table, under its own heading level.
    assert page.text.count('<h3 class="funding__title">') == 2
    # The opener badge doesn't vary by strategy — it repeats once per table.
    assert page.text.count('<div class="badge') == 2
    assert page.text.count("+$9.20, balance $1009.20") == 2

    stored = session.scalars(select(Simulation)).all()
    assert len(stored) == 2
    assert stored[0].run_group is not None
    assert stored[0].run_group == stored[1].run_group


async def test_comparison_page_collapses_only_the_breakeven_ladder(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/simulator",
        data={**REFERENCE_FORM, "strategies": ["adder_breakeven", "double"]},
    )
    page = await client.get(response.headers["location"])
    body = page.text

    # Both tiles stay in the summary strip — the demotion never touches it.
    assert body.count('<li class="stat') == 2
    assert body.count('<details class="ladder-reveal">') == 1
    assert "Show the ladder" in body


async def test_single_run_page_never_collapses_its_ladder(client: AsyncClient) -> None:
    response = await client.post(
        "/simulator", data={**REFERENCE_FORM, "strategies": ["adder_breakeven"]}
    )
    page = await client.get(response.headers["location"])

    assert "ladder-reveal" not in page.text


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
        "/simulator", data={**REFERENCE_FORM, "capital": "-50", "risk_percent": "0.75"}
    )

    assert response.status_code == 422
    body = response.text
    assert 'id="capital-error"' in body
    assert 'value="-50"' in body  # the submitted value is preserved
    assert 'value="0.75"' in body  # ...and so are the ones that were fine


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
    """max_entries is the one remaining field under Advanced."""
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


async def test_history_shows_the_risk_each_opener_was_sized_at(client: AsyncClient) -> None:
    await client.post("/simulator", data={**REFERENCE_FORM, "risk_percent": "0.25"})

    listed = await client.get("/history")

    assert '<th scope="col" class="num">Risk</th>' in listed.text
    assert "0.25%" in listed.text


async def test_a_missing_run_renders_a_page_not_a_json_body(client: AsyncClient) -> None:
    response = await client.get("/results/9999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


async def test_the_current_page_is_marked_in_the_nav(client: AsyncClient) -> None:
    response = await client.get("/simulator")

    assert 'href="/simulator" aria-current="page"' in response.text


async def test_the_stylesheet_url_changes_when_the_stylesheet_does(client: AsyncClient) -> None:
    # Pretend app.css was just edited, and check the page now links to a new URL.
    # If the URL stayed the same, browsers could keep showing the old stylesheet.
    from app.web.templates import STATIC_DIR

    stylesheet = STATIC_DIR / "css" / "app.css"
    before = (await client.get("/history")).text
    stat = stylesheet.stat()
    try:
        os.utime(stylesheet, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        after = (await client.get("/history")).text
    finally:
        os.utime(stylesheet, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    link = re.compile(r'href="[^"]*/css/app\.css\?v=(\d+)"')
    old, new = link.search(before), link.search(after)
    assert old and new
    assert old.group(1) != new.group(1)
