"""Version 1 of the JSON API.

The version prefix appears here and nowhere else. A version string inside a
route decorator is the start of a service that cannot be versioned later.
"""

from fastapi import APIRouter

from .routers import health, ladders, openers, run_groups, simulations, strategies

router = APIRouter(prefix="/api/v1")
router.include_router(health.router, tags=["health"])
router.include_router(simulations.router, tags=["simulations"])
router.include_router(run_groups.router, tags=["run groups"])
router.include_router(ladders.router, tags=["ladders"])
router.include_router(openers.router, tags=["openers"])
router.include_router(strategies.router, tags=["strategies"])

__all__ = ["router"]
