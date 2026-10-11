"""The opening entries: what they return if they win.

A pure read of its query — nothing is simulated or stored.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from ....schemas import OpenerBadgeQuery, OpenerBadgeRead
from ....services import presentation
from ..responses import INVALID_REQUEST

router = APIRouter(prefix="/openers")


@router.get(
    "/badge",
    response_model=OpenerBadgeRead,
    responses=INVALID_REQUEST,
    summary="What the openers return if every one of them wins",
)
def read_opener_badge(query: Annotated[OpenerBadgeQuery, Query()]) -> OpenerBadgeRead:
    return presentation.opener_badge_read(query)
