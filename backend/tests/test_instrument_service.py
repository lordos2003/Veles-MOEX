"""InstrumentService tests (in-memory SQLite async session; no DB/network)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import Integer, MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.brokers import InvalidRequestError
from app.brokers.base import REAL_EXCHANGE_MOEX, BrokerInstrument
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
    real_exchange: str = REAL_EXCHANGE_MOEX,
    first_1min_candle_date: datetime | None = None,
    first_1day_candle_date: datetime | None = None,
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
        real_exchange=real_exchange,
        is_active=is_active,
        first_1min_candle_date=first_1min_candle_date,
        first_1day_candle_date=first_1day_candle_date,
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
async def test_upsert_stores_first_candle_dates_then_none(session) -> None:
    # MVP-7.6 (H2): the broker-reported earliest history is stored; a value is
    # overwritten by a re-sync; no value from the broker -> NULL, never a
    # substituted default. (SQLite keeps datetimes naive — compare that way.)
    service = InstrumentService(session)
    first = await service.upsert_from_broker(
        _broker_instrument(
            "F1",
            "AAA",
            first_1min_candle_date=datetime(2020, 2, 7, 0, 0),
            first_1day_candle_date=datetime(1998, 1, 1, 0, 0),
        )
    )
    await session.commit()
    assert first.first_1min_candle_date == datetime(2020, 2, 7, 0, 0)
    assert first.first_1day_candle_date == datetime(1998, 1, 1, 0, 0)

    # Re-sync with no broker facts -> fields become NULL (not left stale).
    updated = await service.upsert_from_broker(_broker_instrument("F1", "AAA"))
    await session.commit()
    assert updated.first_1min_candle_date is None
    assert updated.first_1day_candle_date is None

    # A second instrument without facts stays NULL after sync.
    other = await service.upsert_from_broker(_broker_instrument("F2", "BBB"))
    await session.commit()
    assert other.first_1min_candle_date is None
    assert other.first_1day_candle_date is None


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


@pytest.mark.asyncio
async def test_sync_from_broker_keeps_only_moex(session) -> None:
    # P8 (MVP-7.3): the sync keeps instruments with the official T-Invest
    # RealExchange enum REAL_EXCHANGE_MOEX only. Samples mirror the live
    # sandbox catalog: MOEX share (TQBR) -> MOEX, SPB-listed/foreign share
    # (e.g. CK Hutchison Holdings, hkd) -> REAL_EXCHANGE_RTS.
    service = InstrumentService(session)
    broker = _SyncBroker(
        [
            _broker_instrument("F1", "TQBR"),
            _broker_instrument("F2", "SBER"),
            _broker_instrument(
                "F3",
                "CKC",
                real_exchange="REAL_EXCHANGE_RTS",
            ),
        ]
    )
    count = await service.sync_from_broker(broker, "share")
    assert count == 2
    rows = await service.list()
    assert {row.figi for row in rows} == {"F1", "F2"}


@pytest.mark.asyncio
async def test_sync_from_broker_deactivates_missing_rows(session) -> None:
    # P8 (MVP-7.3): rows of the synced kind that the broker no longer returns
    # after the MOEX filter (previously synced foreign papers) are deactivated,
    # not deleted: they vanish from active=true pick lists, historical
    # references stay intact, no data migration.
    service = InstrumentService(session)
    await service.upsert_from_broker(_broker_instrument("F1", "AAA"))
    await service.upsert_from_broker(_broker_instrument("F2", "BBB"))
    await session.commit()

    broker = _SyncBroker([_broker_instrument("F1", "AAA")])
    count = await service.sync_from_broker(broker, "share")
    assert count == 1

    active = await service.list(active=True)
    assert [row.figi for row in active] == ["F1"]
    inactive = await service.list(active=False)
    assert [row.figi for row in inactive] == ["F2"]


@pytest.mark.asyncio
async def test_sync_from_broker_empty_response_keeps_rows(session) -> None:
    # U8: an empty broker catalog must not silently deactivate previously
    # synced instruments — the sync raises a clear error, rows stay intact.
    service = InstrumentService(session)
    await service.upsert_from_broker(_broker_instrument("F1", "AAA"))
    await service.upsert_from_broker(_broker_instrument("F2", "BBB"))
    await session.commit()

    with pytest.raises(InvalidRequestError) as excinfo:
        await service.sync_from_broker(_SyncBroker([]), "share")
    assert "справочник брокера пуст, записи не изменены" in str(excinfo.value)

    active = await service.list(active=True)
    assert {row.figi for row in active} == {"F1", "F2"}


@pytest.mark.asyncio
async def test_sync_from_broker_no_moex_papers_keeps_rows(session) -> None:
    # U8: a broker response with papers but zero MOEX instruments after the
    # filter is the same situation — clear error, no deactivation.
    service = InstrumentService(session)
    await service.upsert_from_broker(_broker_instrument("F1", "AAA"))
    await session.commit()

    broker = _SyncBroker(
        [_broker_instrument("F9", "FOREIGN", real_exchange="REAL_EXCHANGE_RTS")]
    )
    with pytest.raises(InvalidRequestError) as excinfo:
        await service.sync_from_broker(broker, "share")
    assert "справочник брокера пуст, записи не изменены" in str(excinfo.value)

    active = await service.list(active=True)
    assert [row.figi for row in active] == ["F1"]
    assert await service.list(active=False) == []
