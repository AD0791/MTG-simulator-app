"""Simulate a plan without storing it.

A GET, because the answer is a pure function of the query: nothing is written,
the same query always returns the same ladder, and a client may cache it.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from ....schemas import LadderRead, SimulationCreate
from ....services import presentation
from ..responses import INVALID_REQUEST

router = APIRouter()


@router.get(
    "/ladders",
    response_model=LadderRead,
    responses=INVALID_REQUEST,
    summary="Simulate a plan without storing it",
)
def read_ladder(plan: Annotated[SimulationCreate, Query()]) -> LadderRead:
    return presentation.ladder_read(plan)
