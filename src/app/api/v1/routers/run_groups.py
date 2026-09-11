"""JSON routes for runs submitted together — one plan under several strategies.

A resource of its own rather than `/simulations/groups/...`, which would share
a path segment with `/simulations/{simulation_id}`.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from ....db import SessionDep
from ....schemas import RunGroupCreate, RunGroupRead
from ....services import presentation, simulation_service
from ..responses import INVALID_REQUEST, NOT_FOUND

router = APIRouter(prefix="/run-groups")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=RunGroupRead,
    responses=INVALID_REQUEST,
    summary="Run one plan under one or more strategies and store every result",
)
def create_run_group(plan: RunGroupCreate, session: SessionDep) -> RunGroupRead:
    simulations = simulation_service.run_and_store_group(
        session, plan.to_creates(), target_profit_percent=plan.recorded_target_percent
    )
    return presentation.run_group_read(simulations)


@router.get(
    "/{run_group}",
    response_model=RunGroupRead,
    responses={**NOT_FOUND, **INVALID_REQUEST},
    summary="Read every live run in one comparison, in submission order",
)
def read_run_group(run_group: uuid.UUID, session: SessionDep) -> RunGroupRead:
    simulations = simulation_service.get_group(session, run_group)
    if not simulations:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run group not found")
    return presentation.run_group_read(simulations)


@router.delete(
    "/{run_group}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, **INVALID_REQUEST},
    summary="Clear every run in one comparison (soft delete)",
)
def delete_run_group(run_group: uuid.UUID, session: SessionDep) -> None:
    if not simulation_service.clear_group(session, run_group):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run group not found")
