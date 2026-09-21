"""Broker data service.

Read-only access to account/position/order/deal data from a broker adapter,
with optional filtering. Strategy/Backtest engines and the API use this internal
interface instead of calling the broker adapter directly.
"""

from __future__ import annotations

from app.brokers.base import BrokerAccount, BrokerAdapter, BrokerDeal, BrokerOrder, BrokerPosition


class BrokerDataService:
    """Provides normalized broker data with optional account/FIGI filtering."""

    def __init__(self, broker: BrokerAdapter) -> None:
        self._broker = broker

    async def get_accounts(self) -> list[BrokerAccount]:
        return await self._broker.get_accounts()

    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        return await self._broker.get_account(account_id)

    async def get_positions(
        self, account_id: str | None = None, figi: str | None = None
    ) -> list[BrokerPosition]:
        positions = await self._broker.get_open_positions(account_id)
        if figi:
            positions = [p for p in positions if p.instrument_figi == figi]
        return positions

    async def get_orders(
        self, account_id: str | None = None, figi: str | None = None
    ) -> list[BrokerOrder]:
        orders = await self._broker.get_orders(account_id)
        if figi:
            orders = [o for o in orders if o.instrument_figi == figi]
        return orders

    async def get_deals(
        self, account_id: str | None = None, figi: str | None = None
    ) -> list[BrokerDeal]:
        deals = await self._broker.get_deals(account_id)
        if figi:
            deals = [d for d in deals if d.instrument_figi == figi]
        return deals
