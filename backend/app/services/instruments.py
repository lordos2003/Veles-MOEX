"""Instrument service / repository.

Internal source of truth for instruments (PostgreSQL). The broker adapter hands
out normalized ``BrokerInstrument`` objects; this service persists them and
reads them back for the API/domain, guaranteeing a single row per FIGI.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers import InvalidRequestError
from app.brokers.base import REAL_EXCHANGE_MOEX, BrokerAdapter, BrokerInstrument
from app.domain.instrument import InstrumentType
from app.models.instrument import Instrument


class InstrumentService:
    """Read/write instrument access bound to an async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_figi(self, figi: str) -> Instrument | None:
        result = await self._session.execute(select(Instrument).where(Instrument.figi == figi))
        return result.scalar_one_or_none()

    async def get_by_id(self, instrument_id: int) -> Instrument | None:
        return await self._session.get(Instrument, instrument_id)

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

        Only MOEX instruments are kept (P8, MVP-7.3): the project works solely
        with Moscow Exchange papers, and T-Invest's free-text ``exchange`` is a
        trading-schedule value (e.g. ``moex_morning_weekend``), not a market.
        The reliable marker is the official ``realExchange`` enum
        (``REAL_EXCHANGE_MOEX`` = «Московская биржа», proto/instruments.proto).
        Verified against the live sandbox catalog (MOEX shares TQBR/MTQR →
        ``REAL_EXCHANGE_MOEX``; SPB-listed and foreign shares → RTS/UNSPECIFIED).

        Existing FIGIs are updated, new ones are created. Rows of the same
        instrument kind that the broker no longer returns (after the filter —
        i.e. previously synced foreign/delisted papers) are deactivated, not
        deleted, so they disappear from the ``active=true`` pick lists without
        a data migration and without touching historical references.
        """
        broker_instruments = await broker.get_instruments(kind)
        moex = [i for i in broker_instruments if i.real_exchange == REAL_EXCHANGE_MOEX]
        if not moex:
            # U8: an empty broker catalog (or no MOEX papers after the filter)
            # must not silently deactivate previously synced instruments.
            raise InvalidRequestError("справочник брокера пуст, записи не изменены")
        seen = {item.figi for item in moex}
        for item in moex:
            await self.upsert_from_broker(item)
        await self._deactivate_missing(kind, seen)
        await self._session.commit()
        return len(moex)

    async def _deactivate_missing(self, kind: str | None, seen: set[str]) -> None:
        """Deactivate rows of the synced kind that the broker did not return."""
        type_value = (kind or "share").upper()
        result = await self._session.execute(
            select(Instrument).where(
                Instrument.instrument_type == type_value,
                Instrument.is_active.is_(True),
            )
        )
        for row in result.scalars():
            if row.figi not in seen:
                row.is_active = False
                await self._session.flush()
