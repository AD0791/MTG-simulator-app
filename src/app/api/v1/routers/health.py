"""Liveness check.

It lives under `/api/v1` like everything else that returns JSON. A health check
that "obviously won't change" is still a contract someone automates against.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas.health import Health

router = APIRouter()


@router.get("/health", response_model=Health, summary="Liveness check")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    return Health(status="ok", app=settings.app_name)
