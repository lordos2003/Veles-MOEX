"""Typed errors for the T-Invest integration.

These are safe for the API layer: no raw SDK exceptions or secrets are leaked.
The error taxonomy maps cleanly onto HTTP status codes (see task section 6).
"""

from __future__ import annotations

from app.brokers.base import BrokerTransportError


class TInvestError(Exception):
    """Base class for all T-Invest integration errors."""

    http_status: int = 502


class AuthenticationError(TInvestError):
    """Invalid/expired API token."""

    http_status = 401


class BrokerConnectionError(TInvestError, BrokerTransportError):
    """Network/connection failure to the T-Invest API.

    MVP-6.13 (S4): also a broker-neutral |BrokerTransportError| so the live
    cycle scheduler classifies connection/timeout failures as transient without
    importing a broker package.
    """

    http_status = 503


class RateLimitError(TInvestError, BrokerTransportError):
    """Too many requests (HTTP 429) — transient by nature."""

    http_status = 429


class InvalidRequestError(TInvestError):
    """Malformed/invalid request (HTTP 400)."""

    http_status = 400


class ResourceNotFoundError(TInvestError):
    """A requested resource was not found (HTTP 404)."""

    http_status = 404


class InstrumentNotFoundError(ResourceNotFoundError):
    """Requested instrument not found."""


class AccountNotFoundError(ResourceNotFoundError):
    """Requested account not found."""


class MarketDataError(BrokerConnectionError):
    """Error while fetching market data."""

    http_status = 502


class BrokerApiError(TInvestError, BrokerTransportError):
    """Unexpected upstream error (HTTP 5xx) — transient by nature."""

    http_status = 502
