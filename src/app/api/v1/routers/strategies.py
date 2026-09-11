"""The strategies the simulator runs, with the names a reader sees."""

from fastapi import APIRouter

from ....schemas import StrategyRead
from ....services import presentation

router = APIRouter()


@router.get(
    "/strategies",
    response_model=list[StrategyRead],
    summary="List every strategy, in the order the form offers them",
)
def list_strategies() -> list[StrategyRead]:
    return presentation.strategies()
