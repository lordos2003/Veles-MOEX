"""API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import backtests, bots, health, sandbox, strategies, tinvest

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tinvest.router)
api_router.include_router(sandbox.router)
api_router.include_router(strategies.router)
api_router.include_router(bots.router)
api_router.include_router(backtests.router)
