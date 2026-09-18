"""TInvestAdapter stub.

The T-Invest API is intentionally NOT wired yet. This class exists so the
|TradingEngine| can operate against the |BrokerAdapter| interface without
depending on T-Invest specifics. Every method raises ``NotImplementedError``
until the T-Invest integration is implemented in a later task.
"""

from __future__ import annotations

from app.brokers.base import (
    BrokerAccount,
    BrokerAdapter,
    BrokerDeal,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)

_NOT_IMPLEMENTED = "T-Invest API integration is not implemented yet"


class TInvestAdapter(BrokerAdapter):
    """Placeholder T-Invest adapter. No network/credentials yet."""

    async def connect(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def close(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_order(self, order_id: str) -> BrokerOrder:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_open_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_deals(self, account_id: str | None = None) -> list[BrokerDeal]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
