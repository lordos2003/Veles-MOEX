"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Basic liveness probe. Does not require a database connection."""
    return HealthResponse(status="ok")
