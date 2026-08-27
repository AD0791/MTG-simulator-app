"""The HTML surface.

These paths are **not** versioned. Versioning protects consumers you do not
control; the only consumer here is the browser being served, and these addresses
are things people bookmark.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError

from ..db import SessionDep
from ..schemas import RawSimulationForm, SimulationForm
from ..services import simulation_service
from ..web import bands, form_errors
from ..web.templates import templates

router = APIRouter(include_in_schema=False)

DEFAULT_FORM = RawSimulationForm(
    capital="1000",
    payout_percent="92",
    entry_1a="5",
    entry_1b="5",
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
    "target_profit_percent",
    "entry_1a",
    "entry_1b",
    "strategies",
}


def _see_other(path: str) -> RedirectResponse:
    """303, so reloading the destination re-reads a stored run instead of resubmitting."""
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", summary="Theory and FAQ")
def index(request: Request) -> Response:
    example_ladder, example_wall = bands.worked_example("adder_profit")
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
            # Identical for both tables — the openers are shared and neither
            # strategy has acted yet.
            "badge": bands.opener_badge(
                config.capital,
                config.entry_1a,
                config.entry_1b,
                config.payout_ratio,
                config.target_profit,
            ),
        },
    )


@router.get("/simulator", summary="The staking plan form")
def simulator(request: Request) -> Response:
    return _form(request, DEFAULT_FORM.model_dump(), {})


@router.post("/simulator", summary="Run one or more strategies, or suggest openers from a target")
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
        return _form(request, values, form_errors.from_validation(exc), rejected=True)

    if submitted.action == "suggest":
        return _suggest_openers(request, values, form)

    try:
        simulations = simulation_service.run_and_store_group(
            session,
            form.to_creates(),
            target_profit_percent=form.target_profit_percent
            if form.target_profit_percent > 0
            else None,
        )
    except ValueError as exc:
        return _form(request, values, form_errors.from_domain(exc, values), rejected=True)

    # One strategy behaves exactly as a single run always has. More than one
    # redirects to the comparison view instead of the individual result.
    if len(simulations) == 1:
        return _see_other(f"/results/{simulations[0].id}")
    return _see_other(f"/results/group/{simulations[0].run_group}")


def _suggest_openers(request: Request, values: dict[str, Any], form: SimulationForm) -> Response:
    """Recompute entry_1a/entry_1b from the target and show the arithmetic in
    a dialog. Never runs a plan or touches the database — suggest, don't
    seize: the reader can still override the filled-in values before actually
    submitting."""
    calc = bands.opener_derivation(form.target_profit, form.payout_percent / 100)
    if calc is not None:
        values = {**values, "entry_1a": str(calc.opener), "entry_1b": str(calc.opener)}

    # Pressing Suggest is an explicit "help me set this up" gesture, so it may
    # reasonably pre-check the strategies the target makes worth comparing.
    # This must stay scoped to this path only: a plain Run submission must
    # never rewrite the reader's checkboxes, or unchecking a box and running
    # would stop meaning what it says. At 0% the defaults are left alone —
    # adder_profit isn't offered at all there, being identical to breakeven.
    #
    # Gated on `calc`, not on the percentage: a percentage of a zero or absent
    # capital resolves to a zero target, which derives no openers. Asking the
    # percentage instead would tick every box while the dialog says there is no
    # target to work from — the two halves of one button contradicting.
    if calc is not None:
        values = {**values, "strategies": ALL_STRATEGIES}

    return _form(request, values, {}, calc=calc, show_calc=True)


def _form(
    request: Request,
    values: dict[str, Any],
    errors: dict[str, str],
    *,
    rejected: bool = False,
    calc: bands.OpenerDerivation | None = None,
    show_calc: bool = False,
) -> Response:
    """Render the form. A rejected submission keeps its values and opens the
    panel holding the offending input. `show_calc` opens the Suggest dialog;
    `calc` being None with `show_calc` set is a real state — no target was
    set, and the dialog says so rather than staying silent."""
    return templates.TemplateResponse(
        request,
        "simulator.html",
        {
            "values": values,
            "errors": errors,
            "advanced_open": bool(set(errors) - PRIMARY_FIELDS - {"__form__"}),
            "badge": _preview_badge(values),
            "calc": calc,
            "show_calc": show_calc,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if rejected else status.HTTP_200_OK,
    )


def _preview_badge(values: dict[str, Any]) -> bands.OpenerBadge:
    """What the currently-typed entry_1a/entry_1b are worth, recomputed on
    every render — tolerant of blank or unparsed values, since this renders
    before anything has necessarily been validated."""
    capital = _safe_float(values.get("capital"))
    return bands.opener_badge(
        capital,
        _safe_float(values.get("entry_1a")),
        _safe_float(values.get("entry_1b")),
        _safe_float(values.get("payout_percent")) / 100,
        capital * _safe_float(values.get("target_profit_percent")) / 100,
    )


def _safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value else default
    except ValueError:
        return default


@router.get("/results/{simulation_id}", summary="One run's ladder")
def results(request: Request, simulation_id: int, session: SessionDep) -> Response:
    simulation = simulation_service.get_simulation(session, simulation_id)
    if simulation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That run is not available.")

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "simulation": simulation,
            "ladder": bands.ladder(simulation.entries, simulation.capital),
            "wall": bands.wall(simulation),
            "strategy_label": bands.STRATEGY_LABELS.get(simulation.strategy, simulation.strategy),
            "badge": bands.opener_badge(
                simulation.capital,
                simulation.entry_1a,
                simulation.entry_1b,
                simulation.payout_ratio,
                simulation.target_profit,
            ),
        },
    )


@router.get("/results/group/{run_group}", summary="Several strategies compared side by side")
def results_group(request: Request, run_group: uuid.UUID, session: SessionDep) -> Response:
    simulations = simulation_service.get_group(session, run_group)
    if not simulations:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That comparison is not available.")

    tables = [
        {
            "simulation": simulation,
            "ladder": bands.ladder(simulation.entries, simulation.capital),
            "wall": bands.wall(simulation),
            "label": bands.STRATEGY_LABELS.get(simulation.strategy, simulation.strategy),
            "badge": bands.opener_badge(
                simulation.capital,
                simulation.entry_1a,
                simulation.entry_1b,
                simulation.payout_ratio,
                simulation.target_profit,
            ),
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
