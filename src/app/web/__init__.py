"""The unversioned HTML surface."""

from fastapi import APIRouter

from . import pages, planner, site

router = APIRouter()
router.include_router(pages.router)
router.include_router(planner.router)
router.include_router(site.router)

__all__ = ["router"]
