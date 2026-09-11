"""The opening entries: what they return if they win, and how to size them to a target.

Both are pure reads of their query — nothing is simulated or stored.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from ....schemas import (
    OpenerBadgeQuery,
    OpenerBadgeRead,
    OpenerSuggestionQuery,
    OpenerSuggestionRead,
)
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


@router.get(
    "/suggestion",
    response_model=OpenerSuggestionRead,
    responses=INVALID_REQUEST,
    summary="The smallest equal openers that clear a target, with the working",
)
def read_opener_suggestion(
    query: Annotated[OpenerSuggestionQuery, Query()],
) -> OpenerSuggestionRead:
    return presentation.opener_suggestion_read(query)
