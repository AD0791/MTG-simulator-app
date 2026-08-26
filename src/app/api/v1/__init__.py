"""Version 1 of the JSON API.

The version prefix appears here and nowhere else. A version string inside a
route decorator is the start of a service that cannot be versioned later.
"""

from fastapi import APIRouter

from .routers import health, simulations

router = APIRouter(prefix="/api/v1")
router.include_router(health.router, tags=["health"])
router.include_router(simulations.router, tags=["simulations"])

__all__ = ["router"]
