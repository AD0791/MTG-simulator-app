"""The HTML surface.

These paths are **not** versioned. Versioning protects consumers you do not
control; the only consumer here is the browser being served, and these addresses
are things people bookmark.
"""

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

DEFAULT_FORM = RawSimulationForm(capital="1000", payout_percent="92", second_entry="18")

# The three inputs shown up front; everything else lives under Advanced.
PRIMARY_FIELDS = {"capital", "payout_percent", "second_entry"}


def _see_other(path: str) -> RedirectResponse:
    """303, so reloading the destination re-reads a stored run instead of resubmitting."""
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", summary="Theory and FAQ")
def index(request: Request) -> Response:
    example_ladder, example_wall = bands.worked_example()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "config": bands.REFERENCE_CONFIG,
            "ladder": example_ladder,
            "wall": example_wall,
        },
    )


@router.get("/simulator", summary="The staking plan form")
def simulator(request: Request) -> Response:
    return _form(request, DEFAULT_FORM.model_dump(), {})


@router.post("/simulator", summary="Run a plan and redirect to its result")
def submit_simulator(
    request: Request,
    session: SessionDep,
    submitted: Annotated[RawSimulationForm, Form()],
) -> Response:
    values = submitted.model_dump()

    # One try/except, in one place. The HTML surface needs the rejection rendered
    # beside the offending input with the reader's values intact, which the
    # app-wide problem+json seam cannot do. The rules themselves are not
    # restated — `SimulationForm` checks shape, the domain checks the plan.
    try:
        form = SimulationForm.model_validate(values)
    except ValidationError as exc:
        return _form(request, values, form_errors.from_validation(exc), rejected=True)

    try:
        simulation = simulation_service.run_and_store(session, form.to_create())
    except ValueError as exc:
        return _form(request, values, form_errors.from_domain(exc, values), rejected=True)

    return _see_other(f"/results/{simulation.id}")


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
        },
    )


@router.get("/history", summary="Stored runs")
def history(request: Request, session: SessionDep) -> Response:
    return templates.TemplateResponse(
        request, "history.html", {"simulations": simulation_service.list_simulations(session)}
    )


@router.post("/history/clear", summary="Clear every stored run (soft delete)")
def clear_history(session: SessionDep) -> Response:
    simulation_service.clear_all(session)
    return _see_other("/history")


@router.post("/results/{simulation_id}/delete", summary="Clear one run (soft delete)")
def delete_result(simulation_id: int, session: SessionDep) -> Response:
    simulation_service.clear_simulation(session, simulation_id)
    return _see_other("/history")
