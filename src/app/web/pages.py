"""The HTML surface.

These paths are **not** versioned. Versioning protects consumers you do not
control; the only consumer here is the browser being served, and these addresses
are things people bookmark.
"""

import uuid
from typing import Annotated

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

# The inputs shown up front; everything else lives under Advanced.
PRIMARY_FIELDS = {"capital", "payout_percent", "entry_1a", "entry_1b", "strategies"}


def _see_other(path: str) -> RedirectResponse:
    """303, so reloading the destination re-reads a stored run instead of resubmitting."""
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", summary="Theory and FAQ")
def index(request: Request) -> Response:
    example_ladder, example_wall = bands.worked_example("adder_profit")
    double_ladder, double_wall = bands.worked_example("double")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "config": bands.REFERENCE_CONFIG,
            "ladder": example_ladder,
            "wall": example_wall,
            "double_ladder": double_ladder,
            "double_wall": double_wall,
        },
    )


@router.get("/simulator", summary="The staking plan form")
def simulator(request: Request) -> Response:
    return _form(request, DEFAULT_FORM.model_dump(), {})


@router.post("/simulator", summary="Run one or more strategies and redirect to the result")
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

    try:
        simulations = simulation_service.run_and_store_group(session, form.to_creates())
    except ValueError as exc:
        return _form(request, values, form_errors.from_domain(exc, values), rejected=True)

    # One strategy behaves exactly as a single run always has. More than one
    # redirects to the comparison view instead of the individual result.
    if len(simulations) == 1:
        return _see_other(f"/results/{simulations[0].id}")
    return _see_other(f"/results/group/{simulations[0].run_group}")


def _form(
    request: Request,
    values: dict[str, str],
    errors: dict[str, str],
    *,
    rejected: bool = False,
) -> Response:
    """Render the form. A rejected submission keeps its values and opens the
    panel holding the offending input."""
    return templates.TemplateResponse(
        request,
        "simulator.html",
        {
            "values": values,
            "errors": errors,
            "advanced_open": bool(set(errors) - PRIMARY_FIELDS - {"__form__"}),
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if rejected else status.HTTP_200_OK,
    )


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
            "ladder": bands.ladder(simulation.entries),
            "wall": bands.wall(simulation),
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
            "simulation": simulation,
            "ladder": bands.ladder(simulation.entries),
            "wall": bands.wall(simulation),
            "label": bands.STRATEGY_LABELS.get(simulation.strategy, simulation.strategy),
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
