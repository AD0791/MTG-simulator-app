"""The HTML surface.

These paths are **not** versioned. Versioning protects consumers you do not
control; the only consumer here is the browser being served, and these addresses
are things people bookmark.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError

from ..db import SessionDep
from ..domain.staking_simulator import InvalidStakingConfig, risk_entry
from ..log import logger
from ..models import Simulation
from ..schemas import RawSimulationForm, SimulationForm
from ..services import bands, simulation_service
from ..web import form_errors, form_state
from ..web.templates import templates

router = APIRouter(include_in_schema=False)

DEFAULT_FORM = RawSimulationForm(
    capital="1000",
    payout_percent="92",
    risk_percent="0.5",
    opener_count="2",
    strategies=["adder_breakeven", "double"],
)

# Every strategy the form offers, in the order its checkboxes appear. Named
# rather than read inline from `STRATEGY_LABELS`, which is a display map and
# should not be doubling as the answer to a question about behaviour.
ALL_STRATEGIES = list(bands.STRATEGY_LABELS)

# The inputs shown up front; everything else lives under Advanced.
PRIMARY_FIELDS = {
    "capital",
    "payout_percent",
    "risk_percent",
    "opener_count",
    "strategies",
}


def _see_other(path: str) -> RedirectResponse:
    """303, so reloading the destination re-reads a stored run instead of resubmitting."""
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", summary="Theory and FAQ")
def index(request: Request) -> Response:
    example_ladder, example_wall = bands.worked_example("adder_breakeven")
    double_ladder, double_wall = bands.worked_example("double")
    config = bands.REFERENCE_CONFIG
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "config": config,
            "ladder": example_ladder,
            "wall": example_wall,
            "double_ladder": double_ladder,
            "double_wall": double_wall,
            "risk_percent": bands.REFERENCE_RISK_PERCENT,
            # Identical for both tables — the openers are shared and neither
            # strategy has acted yet.
            "badge": bands.opener_badge(
                config.capital,
                config.entry_1a,
                config.entry_1b,
                config.payout_ratio,
            ),
        },
    )


@router.get("/simulator", summary="The staking plan form")
def simulator(
    request: Request,
    session: SessionDep,
    run_id: Annotated[str | None, Query(alias="from")] = None,
    group: str | None = None,
) -> Response:
    return _form(request, _prefill(request, session, run_id, group), {})


def _prefill(
    request: Request, session: SessionDep, run_id: str | None, group: str | None
) -> dict[str, Any]:
    """The values the form opens with, from the first source that has them: a
    stored run (`?from=`), a stored comparison (`?group=`), the last successful
    submission's cookie, then the defaults. A source that is missing, cleared,
    recorded before risk sizing existed, or unreadable falls through — never
    an error page."""
    for values in (
        _from_runs(_one_run(session, run_id)),
        _from_runs(_group_runs(session, group)),
        _from_cookie(request.cookies.get(form_state.SIMULATOR_COOKIE)),
    ):
        if values is not None:
            return values
    return DEFAULT_FORM.model_dump()


def _one_run(session: SessionDep, run_id: str | None) -> list[Simulation]:
    if not run_id or not run_id.isdigit():
        return []
    simulation = simulation_service.get_simulation(session, int(run_id))
    return [simulation] if simulation is not None else []


def _group_runs(session: SessionDep, group: str | None) -> Sequence[Simulation]:
    try:
        run_group = uuid.UUID(group) if group else None
    except ValueError:
        return []
    return simulation_service.get_group(session, run_group) if run_group else []


def _from_runs(simulations: Sequence[Simulation]) -> dict[str, Any] | None:
    """The form a stored run was submitted with; every strategy in a group is checked."""
    first = simulations[0] if simulations else None
    if first is None or first.risk_percent is None:
        return None
    return RawSimulationForm(
        capital=_plain(first.capital),
        payout_percent=_plain(first.payout_ratio * 100),
        risk_percent=_plain(first.risk_percent),
        opener_count="1" if first.entry_1b is None else "2",
        max_entries=str(first.max_entries),
        strategies=[simulation.strategy for simulation in simulations],
    ).model_dump()


def _from_cookie(saved: str | None) -> dict[str, Any] | None:
    if not saved:
        return None
    parsed = parse_qs(saved, keep_blank_values=True)
    data: dict[str, Any] = {key: values[0] for key, values in parsed.items()}
    data["strategies"] = parsed.get("strategies", [])
    try:
        return RawSimulationForm.model_validate(data).model_dump()
    except ValidationError:
        return None


def _plain(number: float) -> str:
    """A stored float as a reader would type it: 1234.0 → "1234", a 92% payout → "92"."""
    return format(Decimal(repr(round(number, 6))).normalize(), "f")


@router.post("/simulator", summary="Run one or more strategies")
def submit_simulator(
    request: Request,
    session: SessionDep,
    submitted: Annotated[RawSimulationForm, Form()],
) -> Response:
    values = submitted.model_dump()

    # One try/except, in one place. The HTML surface needs the rejection rendered
    # beside the offending input with the reader's values intact, which the
    # app-wide problem+json seam cannot do. The rules themselves are not
    # restated — `SimulationForm` checks shape, the domain checks each plan.
    try:
        form = SimulationForm.model_validate(values)
    except ValidationError as exc:
        errors = form_errors.from_validation(exc)
        # Field names, never the values. The names are what diagnose a form
        # that keeps being rejected; the values are the reader's own figures.
        logger.info("form.rejected", stage="shape", fields=sorted(errors))
        return _form(request, values, errors, rejected=True)

    # The same conversion `POST /api/v1/run-groups` receives already made.
    plan = form.to_plan()
    try:
        simulations = simulation_service.run_and_store_group(session, plan.to_creates())
    except ValueError as exc:
        errors = form_errors.from_domain(exc)
        # This arm catches the domain rejection, so `plan.rejected` in main.py
        # never fires for a form submission. Without this line the HTML surface
        # would record nothing at all.
        logger.info("form.rejected", stage="plan", fields=sorted(errors), detail=str(exc))
        return _form(request, values, errors, rejected=True)

    # One strategy behaves exactly as a single run always has. More than one
    # redirects to the comparison view instead of the individual result.
    if len(simulations) == 1:
        response = _see_other(f"/results/{simulations[0].id}")
    else:
        response = _see_other(f"/results/group/{simulations[0].run_group}")
    # So a bare /simulator opens with these values next time.
    form_state.remember(
        response,
        request,
        form_state.SIMULATOR_COOKIE,
        urlencode(values, doseq=True),
        form_state.FORM_MAX_AGE,
    )
    return response


def _form(
    request: Request,
    values: dict[str, Any],
    errors: dict[str, str],
    *,
    rejected: bool = False,
) -> Response:
    """Render the form. A rejected submission keeps its values and opens the
    panel holding the offending input."""
    entry = _preview_entry(values)
    return templates.TemplateResponse(
        request,
        "simulator.html",
        {
            "values": values,
            "errors": errors,
            "advanced_open": bool(set(errors) - PRIMARY_FIELDS - {"__form__"}),
            "opener_entry": entry,
            "badge": _preview_badge(values, entry),
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if rejected else status.HTTP_200_OK,
    )


def _preview_entry(values: dict[str, Any]) -> float | None:
    """The opening entry the typed capital and risk size, by the domain's own
    rule — or None when they size no entry yet. Tolerant of blank or unparsed
    values, since this renders before anything has necessarily been validated."""
    try:
        return risk_entry(
            _safe_float(values.get("capital")), _safe_float(values.get("risk_percent"))
        )
    except InvalidStakingConfig:
        return None


def _preview_badge(values: dict[str, Any], entry: float | None) -> bands.OpenerBadge:
    """What the previewed openers are worth if they win, recomputed on every render."""
    opener = entry or 0.0
    return bands.opener_badge(
        _safe_float(values.get("capital")),
        opener,
        opener if values.get("opener_count") != "1" else None,
        _safe_float(values.get("payout_percent")) / 100,
    )


def _safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value else default
    except ValueError:
        return default


def _run_view(simulation: Simulation) -> dict[str, Any]:
    """Everything one stored run renders with — its ladder, wall, funding
    table and opener badge — assembled once for both results pages."""
    ladder = bands.ladder(simulation.entries, simulation.capital)
    wall = bands.wall(simulation)
    return {
        "simulation": simulation,
        "ladder": ladder,
        "wall": wall,
        "funding": bands.funding(bands.config_of(simulation)),
        "badge": bands.opener_badge(
            simulation.capital,
            simulation.entry_1a,
            simulation.entry_1b,
            simulation.payout_ratio,
        ),
    }


@router.get("/results/{simulation_id}", summary="One run's ladder")
def results(request: Request, simulation_id: int, session: SessionDep) -> Response:
    simulation = simulation_service.get_simulation(session, simulation_id)
    if simulation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That run is not available.")

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            **_run_view(simulation),
            "strategy_label": bands.STRATEGY_LABELS.get(simulation.strategy, simulation.strategy),
        },
    )


@router.get("/results/group/{run_group}", summary="Several strategies compared side by side")
def results_group(request: Request, run_group: uuid.UUID, session: SessionDep) -> Response:
    simulations = simulation_service.get_group(session, run_group)
    if not simulations:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That comparison is not available.")

    tables = [
        {
            **_run_view(simulation),
            "label": bands.STRATEGY_LABELS.get(simulation.strategy, simulation.strategy),
            # Breakeven recovery returns the debt and roughly nothing more; it
            # stays on the comparison page as the honest contrast but its
            # ladder is collapsed so it isn't a co-headline with the other two.
            "collapsed": simulation.strategy == "adder_breakeven",
        }
        for simulation in simulations
    ]
    return templates.TemplateResponse(
        request,
        "results_group.html",
        {"run_group": run_group, "tables": tables},
    )


@router.get("/history", summary="Stored runs")
def history(request: Request, session: SessionDep) -> Response:
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "simulations": simulation_service.list_simulations(session),
            "strategy_labels": bands.STRATEGY_LABELS,
        },
    )


@router.post("/history/clear", summary="Clear every stored run (soft delete)")
def clear_history(session: SessionDep) -> Response:
    simulation_service.clear_all(session)
    return _see_other("/history")


@router.post("/results/{simulation_id}/delete", summary="Clear one run (soft delete)")
def delete_result(simulation_id: int, session: SessionDep) -> Response:
    simulation_service.clear_simulation(session, simulation_id)
    return _see_other("/history")


@router.post("/results/group/{run_group}/delete", summary="Clear a comparison (soft delete)")
def delete_group(run_group: uuid.UUID, session: SessionDep) -> Response:
    simulation_service.clear_group(session, run_group)
    return _see_other("/history")
