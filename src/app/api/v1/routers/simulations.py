"""JSON routes for simulations.

Controllers only: resolve dependencies, delegate, return. No arithmetic, no
domain branching, and no `try/except` around the simulator — an invalid plan
raises `ValueError` and the app-wide handler turns it into a problem response.
"""

from fastapi import APIRouter, HTTPException, status

from ....db import SessionDep
from ....schemas import SimulationCreate, SimulationRead, SimulationSummary
from ....services import presentation, simulation_service
from ..responses import INVALID_REQUEST, NOT_FOUND

router = APIRouter(prefix="/simulations")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SimulationRead,
    responses=INVALID_REQUEST,
    summary="Run a staking plan and store the result",
)
def create_simulation(payload: SimulationCreate, session: SessionDep) -> SimulationRead:
    simulation = simulation_service.run_and_store(session, payload)
    return presentation.simulation_read(simulation)


@router.get("", response_model=list[SimulationSummary], summary="List stored runs")
def list_simulations(session: SessionDep) -> list[SimulationSummary]:
    simulations = simulation_service.list_simulations(session)
    return [SimulationSummary.model_validate(s) for s in simulations]


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear every stored run (soft delete)",
)
def clear_simulations(session: SessionDep) -> None:
    simulation_service.clear_all(session)


@router.get(
    "/{simulation_id}",
    response_model=SimulationRead,
    responses={**NOT_FOUND, **INVALID_REQUEST},
    summary="Read one stored run with its ladder",
)
def read_simulation(simulation_id: int, session: SessionDep) -> SimulationRead:
    simulation = simulation_service.get_simulation(session, simulation_id)
    if simulation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Simulation not found")
    return presentation.simulation_read(simulation)


@router.delete(
    "/{simulation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, **INVALID_REQUEST},
    summary="Clear one stored run (soft delete)",
)
def delete_simulation(simulation_id: int, session: SessionDep) -> None:
    if not simulation_service.clear_simulation(session, simulation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Simulation not found")
