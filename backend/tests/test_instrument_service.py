"""InstrumentService tests (in-memory SQLite async session; no DB/network)."""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import Integer, MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.brokers.base import BrokerInstrument
from app.domain.instrument import InstrumentType, TradingStatus
from app.models import Instrument
from app.services.instruments import InstrumentService


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Clone the Instrument table and use an Integer PK so SQLite auto-increments
    # (SQLite does not auto-increment a BIGINT primary key).
    cloned = Instrument.__table__.to_metadata(MetaData())
    for col in cloned.columns:
        if col.primary_key and isinstance(col.type, sa.BigInteger):
            col.type = Integer()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: cloned.create(c))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


def _broker_instrument(
    figi: str,
    ticker: str,
    instrument_type: InstrumentType = InstrumentType.SHARE,
    is_active: bool = True,
) -> BrokerInstrument:
    return BrokerInstrument(
        figi=figi,
        ticker=ticker,
        name=f"{ticker} name",
        instrument_type=instrument_type,
        currency="RUB",
        lot_size=10,
        tick_size=Decimal("0.01"),
        trading_status=TradingStatus.TRADING_AVAILABLE
        if is_active
        else TradingStatus.TRADING_UNAVAILABLE,
        exchange="MOEX",
        is_active=is_active,
    )


class _SyncBroker:
    def __init__(self, instruments: list[BrokerInstrument]) -> None:
        self._instruments = instruments
        self.calls = 0

    async def get_instruments(self, kind: str | None = None) -> list[BrokerInstrument]:
        self.calls += 1
        return self._instruments


@pytest.mark.asyncio
async def test_upsert_creates_then_updates_no_duplicate(session) -> None:
    service = InstrumentService(session)
    first = await service.upsert_from_broker(_broker_instrument("F1", "AAA"))
    assert first.figi == "F1"
    assert first.instrument_type == "SHARE"

    # Second sync with changed fields must update, not duplicate.
    updated = await service.upsert_from_broker(_broker_instrument("F1", "AAA2", is_active=False))
    await session.commit()
    assert updated.figi == "F1"
    assert updated.ticker == "AAA2"
    assert updated.is_active is False

    rows = await service.list()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_by_figi_and_ticker(session) -> None:
    service = InstrumentService(session)
    await service.upsert_from_broker(_broker_instrument("F1", "AAA"))
    await session.commit()

    by_figi = await service.get_by_figi("F1")
    assert by_figi is not None
    assert by_figi.ticker == "AAA"

    by_ticker = await service.get_by_ticker("AAA")
    assert by_ticker is not None
    assert by_ticker.figi == "F1"

    assert await service.get_by_figi("NOPE") is None


@pytest.mark.asyncio
async def test_list_filters(session) -> None:
    service = InstrumentService(session)
    await service.upsert_from_broker(_broker_instrument("F1", "AAA", InstrumentType.SHARE))
    await service.upsert_from_broker(_broker_instrument("F2", "BBB", InstrumentType.BOND))
    await service.upsert_from_broker(
        _broker_instrument("F3", "CCC", InstrumentType.SHARE, is_active=False)
    )
    await session.commit()

    shares = await service.list(type_=InstrumentType.SHARE)
    assert len(shares) == 2

    active = await service.list(active=True)
    assert len(active) == 2

    by_ticker = await service.list(ticker="BBB")
    assert len(by_ticker) == 1
    assert by_ticker[0].figi == "F2"


@pytest.mark.asyncio
async def test_sync_from_broker_no_duplicates(session) -> None:
    service = InstrumentService(session)
    broker = _SyncBroker(
        [
            _broker_instrument("F1", "AAA"),
            _broker_instrument("F2", "BBB"),
            _broker_instrument("F3", "CCC", is_active=False),
        ]
    )
    count = await service.sync_from_broker(broker, "share")
    assert count == 3
    assert broker.calls == 1

    # Re-synchronize the same set -> still 3 rows in DB, no duplicates.
    count2 = await service.sync_from_broker(broker, "share")
    assert count2 == 3
    rows = await service.list()
    assert len(rows) == 3
