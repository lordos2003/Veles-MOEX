"""Minimal read-only HTTP client for the official T-Invest REST API.

The T-Invest API is gRPC-based; the same service/method contracts are exposed
over a REST gateway. This thin client POSTs to those endpoints and maps error
responses to our own typed errors. It never logs the token or authorization
headers.

Documented endpoints:
- UsersService/GetAccounts
- OperationsService/GetPortfolio
- InstrumentsService/GetInstrumentBy, FindInstrument, Shares/Etfs/Bonds/Currencies/Futures
- MarketDataService/GetLastPrices, GetCandles
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.brokers.tinvest_errors import (
    AuthenticationError,
    BrokerApiError,
    BrokerConnectionError,
    InvalidRequestError,
    RateLimitError,
    ResourceNotFoundError,
)

logger = logging.getLogger(__name__)


class TInvestClient:
    """Thin async REST client for T-Invest read-only endpoints."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://invest-public-api.tbank.ru/rest",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise ValueError("T-Invest token must be provided")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, method_path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST to a T-Invest REST method and return the parsed JSON response."""
        url = f"{self._base_url}/{method_path}"
        logger.debug("tinvest call start method=%s", method_path)
        try:
            response = await self._http.post(
                url,
                json=body or {},
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            logger.debug(
                "tinvest call connection_error method=%s error=%s", method_path, type(exc).__name__
            )
            raise BrokerConnectionError(f"T-Invest connection error: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            self._raise_for_status(response.status_code, method_path)

        logger.debug("tinvest call ok method=%s", method_path)
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - unexpected upstream
            raise BrokerApiError("T-Invest returned non-JSON response") from exc

    def _raise_for_status(self, status_code: int, method_path: str) -> None:
        logger.debug("tinvest call error method=%s status=%s", method_path, status_code)
        if status_code == 401:
            raise AuthenticationError("T-Invest authentication failed")
        if status_code == 429:
            raise RateLimitError("T-Invest rate limit exceeded")
        if status_code == 404:
            raise ResourceNotFoundError(f"T-Invest resource not found: {method_path}")
        if status_code == 400:
            raise InvalidRequestError(f"T-Invest invalid request: {method_path}")
        if 500 <= status_code < 600:
            raise BrokerApiError(f"T-Invest upstream error {status_code}")
        raise BrokerApiError(f"T-Invest unexpected HTTP {status_code}")
