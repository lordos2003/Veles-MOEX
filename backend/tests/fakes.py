"""Test doubles for the T-Invest integration / services (no real token/network)."""

from __future__ import annotations

from typing import Any

from app.brokers.tinvest_errors import TInvestError
from app.domain.instrument import InstrumentType
from app.models.instrument import Instrument


class TInvestFakeClient:
    """Duck-typed stand-in for TInvestClient.

    Returns canned responses keyed by method path, or raises configured errors
    for a given path. No network access.
    """

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        errors: dict[str, TInvestError] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, method_path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method_path, body or {}))
        if method_path in self.errors:
            raise self.errors[method_path]
        return self.responses.get(method_path, {})


class FakeBrokerData:
    """In-memory BrokerAdapter stand-in returning canned broker data."""

    def __init__(
        self,
        accounts: list | None = None,
        positions: list | None = None,
        orders: list | None = None,
        deals: list | None = None,
    ) -> None:
        self._accounts = accounts or []
        self._positions = positions or []
        self._orders = orders or []
        self._deals = deals or []

    async def get_accounts(self) -> list:
        return self._accounts

    async def get_account(self, account_id: str | None = None):
        if self._accounts:
            return self._accounts[0]
        raise ValueError("no account")

    async def get_open_positions(self, account_id: str | None = None) -> list:
        return self._positions

    async def get_orders(self, account_id: str | None = None) -> list:
        return self._orders

    async def get_deals(self, account_id: str | None = None) -> list:
        return self._deals


class FakeInstrumentService:
    """In-memory stand-in for InstrumentService (no DB)."""

    def __init__(self, instruments: list[Instrument] | None = None) -> None:
        self._instruments = {item.figi: item for item in (instruments or [])}

    async def get_by_figi(self, figi: str) -> Instrument | None:
        return self._instruments.get(figi)

    async def get_by_ticker(self, ticker: str) -> Instrument | None:
        for item in self._instruments.values():
            if item.ticker == ticker:
                return item
        return None

    async def list(
        self,
        type_: InstrumentType | None = None,
        active: bool | None = None,
        ticker: str | None = None,
    ) -> list[Instrument]:
        result = list(self._instruments.values())
        if type_ is not None:
            result = [i for i in result if i.instrument_type == type_.value]
        if active is not None:
            result = [i for i in result if i.is_active == active]
        if ticker:
            result = [i for i in result if i.ticker == ticker]
        return result

    async def sync_from_broker(self, broker: object, kind: str | None = None) -> int:
        return 0
