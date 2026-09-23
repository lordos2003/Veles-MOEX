"""Shared domain enums."""

from __future__ import annotations

from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    """Order lifecycle per Architecture & Product Specification section 7."""

    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class BotState(StrEnum):
    """Bot lifecycle states (MVP-6.5)."""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOP_REQUESTED = "STOP_REQUESTED"
    ERROR = "ERROR"
    EMERGENCY_STOP = "EMERGENCY_STOP"
