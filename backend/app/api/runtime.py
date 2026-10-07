"""Read-only runtime mode endpoint (MVP-7.1 U2).

Exposes the application mode (sandbox / live) so the UI can show the mode and
gate bot actions without duplicating configuration knowledge in the frontend.
No mutation is performed and no live-runtime state is read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_settings_dep
from app.core.config import Settings
from app.schemas.runtime import RuntimeResponse

router = APIRouter(tags=["runtime"])


@router.get("/runtime", response_model=RuntimeResponse)
async def runtime_info(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> RuntimeResponse:
    """Return the application mode from settings (read-only)."""
    return RuntimeResponse(
        sandbox=settings.tinvest_sandbox,
        live_trading_enabled=settings.live_trading_enabled,
        tinvest_configured=bool(settings.tinvest_token),
    )
