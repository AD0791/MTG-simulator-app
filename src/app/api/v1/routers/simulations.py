"""JSON routes for simulations.

Controllers only: resolve dependencies, delegate, return. No arithmetic, no
domain branching, and no `try/except` around the simulator — an invalid plan
raises `ValueError` and the app-wide handler turns it into a problem response.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.db import SessionDep
from app.schemas import Problem, SimulationCreate, SimulationRead, SimulationSummary
from app.services import simulation_service

router = APIRouter(prefix="/simulations")

Responses = dict[int | str, dict[str, Any]]

NOT_FOUND: Responses = {
    status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such live run"}
}
INVALID_PLAN: Responses = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": Problem,
        "description": "The staking plan is not a valid configuration",
    }
}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SimulationRead,
    responses=INVALID_PLAN,
    summary="Run a staking plan and store the result",
)
def create_simulation(payload: SimulationCreate, session: SessionDep) -> SimulationRead:
    simulation = simulation_service.run_and_store(session, payload)
    return SimulationRead.model_validate(simulation)


@router.get("", response_model=list[SimulationSummary], summary="List stored runs")
def list_simulations(session: SessionDep) -> list[SimulationSummary]:
    simulations = simulation_service.list_simulations(session)
    return [SimulationSummary.model_validate(s) for s in simulations]


@router.get(
    "/{simulation_id}",
    response_model=SimulationRead,
    responses=NOT_FOUND,
    summary="Read one stored run with its ladder",
)
def read_simulation(simulation_id: int, session: SessionDep) -> SimulationRead:
    simulation = simulation_service.get_simulation(session, simulation_id)
    if simulation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Simulation not found")
    return SimulationRead.model_validate(simulation)


@router.delete(
    "/{simulation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    summary="Clear one stored run (soft delete)",
)
def delete_simulation(simulation_id: int, session: SessionDep) -> None:
    if not simulation_service.clear_simulation(session, simulation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Simulation not found")
