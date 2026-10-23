"""Plan the growth a capital target requires.

A GET, because the answer is a pure function of the query and today's date:
nothing is written, and a client may cache it.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from ....schemas.risk_plan import RiskPlanQuery, RiskPlanRead
from ....services import risk_planner
from ..responses import INVALID_REQUEST

router = APIRouter()


@router.get(
    "/risk-plans",
    response_model=RiskPlanRead,
    responses=INVALID_REQUEST,
    summary="What daily growth and how many wins a capital target requires",
)
def read_risk_plan(query: Annotated[RiskPlanQuery, Query()]) -> RiskPlanRead:
    return risk_planner.plan_read(query, date.today())
