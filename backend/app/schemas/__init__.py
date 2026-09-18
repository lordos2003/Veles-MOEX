"""Pydantic schemas package."""

from __future__ import annotations

from app.schemas.common import Message
from app.schemas.health import HealthResponse

__all__ = ["Message", "HealthResponse"]
