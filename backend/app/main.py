"""Veles-MOEX FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.brokers.tinvest_errors import TInvestError
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend for the Veles-MOEX algorithmic trading platform.",
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
