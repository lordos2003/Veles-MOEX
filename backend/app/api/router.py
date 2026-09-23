"""API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import bots, health, tinvest

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tinvest.router)
api_router.include_router(bots.router)
