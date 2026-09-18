"""Instrument service / repository.

Internal source of truth for instruments (PostgreSQL). The broker adapter hands
out normalized ``BrokerInstrument`` objects; this service persists them and
reads them back for the API/domain, guaranteeing a single row per FIGI.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import BrokerAdapter, BrokerInstrument
from app.domain.instrument import InstrumentType
from app.models.instrument import Instrument


class InstrumentService:
    """Read/write instrument access bound to an async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_figi(self, figi: str) -> Instrument | None:
        result = await self._session.execute(select(Instrument).where(Instrument.figi == figi))
        return result.scalar_one_or_none()

    async def get_by_ticker(self, ticker: str) -> Instrument | None:
        result = await self._session.execute(select(Instrument).where(Instrument.ticker == ticker))
        return result.scalar_one_or_none()

    async def list(
        self,
        type_: InstrumentType | None = None,
        active: bool | None = None,
        ticker: str | None = None,
    ) -> list[Instrument]:
        statement = select(Instrument).order_by(Instrument.ticker)
        if type_ is not None:
            statement = statement.where(Instrument.instrument_type == type_.value)
        if active is not None:
            statement = statement.where(Instrument.is_active == active)
        if ticker:
            statement = statement.where(Instrument.ticker == ticker)
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def upsert_from_broker(self, broker: BrokerInstrument) -> Instrument:
        """Insert or update a single instrument by FIGI (no duplicates)."""
        existing = await self.get_by_figi(broker.figi)
        if existing is None:
            instrument = Instrument(
                figi=broker.figi,
                ticker=broker.ticker,
                name=broker.name,
                instrument_type=broker.instrument_type.value if broker.instrument_type else None,
                currency=broker.currency,
                lot_size=broker.lot_size,
                tick_size=broker.tick_size,
                trading_status=broker.trading_status.value,
                exchange=broker.exchange,
                is_active=broker.is_active,
            )
            self._session.add(instrument)
            await self._session.flush()
            return instrument

        existing.ticker = broker.ticker
        existing.name = broker.name
        existing.instrument_type = broker.instrument_type.value if broker.instrument_type else None
        existing.currency = broker.currency
        existing.lot_size = broker.lot_size
        existing.tick_size = broker.tick_size
        existing.trading_status = broker.trading_status.value
        existing.exchange = broker.exchange
        existing.is_active = broker.is_active
        await self._session.flush()
        return existing

    async def sync_from_broker(self, broker: BrokerAdapter, kind: str | None = None) -> int:
        """Synchronize instruments from the broker into PostgreSQL.

        Existing FIGIs are updated, new ones are created, and inactive status is
        preserved. Returns the number of instruments processed.
        """
        broker_instruments = await broker.get_instruments(kind)
        for item in broker_instruments:
            await self.upsert_from_broker(item)
        await self._session.commit()
        return len(broker_instruments)
