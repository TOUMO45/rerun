"""§12 compliance: `/healthz` must be all green for a fresh deploy to be
considered working end-to-end."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthOut

router = APIRouter()


@router.get("/healthz", response_model=HealthOut)
def healthz() -> HealthOut:
    settings = get_settings()
    return HealthOut(
        status="ok",
        nebius_configured=settings.nebius_configured,
        tavily_configured=settings.tavily_configured,
        demo_mode=settings.demo_mode,
    )
