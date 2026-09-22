"""Veles-MOEX FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.brokers.tinvest_errors import TInvestError
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run live-execution recovery at startup when enabled.

    Live execution is only allowed to resume after a SAFE reconciliation. When
    recovery is blocked the service remains disabled (no new live orders).
    """
    service = None
    if get_settings().live_trading_enabled:
        from app.trading.live_execution import build_live_service

        try:
            service = build_live_service()
            result = await service.start()
            app.state.live_execution = service
            if not result.safe:
                logger.warning("live execution blocked at startup: %s", result.reason)
        except Exception as exc:  # noqa: BLE001 - startup must not crash the API
            logger.exception("live execution recovery failed; live trading disabled: %s", exc)
            service = None
    try:
        yield
    finally:
        if service is not None:
            session = getattr(service, "_session_owner", None)
            if session is not None:
                await session.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend for the Veles-MOEX algorithmic trading platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.exception_handler(TInvestError)
async def tinvest_error_handler(request: Request, exc: TInvestError) -> JSONResponse:
    """Normalize T-Invest errors to HTTP codes; never expose secrets."""
    return JSONResponse(status_code=exc.http_status, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"status": "ok"}
