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


async def test_simulator_shows_three_primary_inputs_and_a_collapsed_panel(
    client: AsyncClient,
) -> None:
    response = await client.get("/simulator")

    assert response.status_code == 200
    body = response.text
    for field in ("capital", "payout_percent", "entry_1a", "entry_1b"):
        assert f'id="{field}"' in body
    for field in ("target_profit", "max_entries"):
        assert f'id="{field}"' in body
    assert '<details class="advanced">' in body  # collapsed: no `open`


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


async def test_a_rejected_plan_keeps_its_values_and_names_the_field(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/simulator", data={**REFERENCE_FORM, "capital": "-50", "target_profit": "7"}
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
    response = await client.post("/simulator", data={**REFERENCE_FORM, "target_profit": "-1"})

    assert response.status_code == 422
    assert '<details class="advanced" open>' in response.text
    assert 'id="target_profit-error"' in response.text


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


async def test_a_missing_run_renders_a_page_not_a_json_body(client: AsyncClient) -> None:
    response = await client.get("/results/9999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


async def test_the_current_page_is_marked_in_the_nav(client: AsyncClient) -> None:
    response = await client.get("/simulator")

    assert 'href="/simulator" aria-current="page"' in response.text
