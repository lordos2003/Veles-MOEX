"""MarketDataService tests (fake broker; no network/DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.brokers import (
    InstrumentNotFoundError,
    InvalidRequestError,
    ResourceNotFoundError,
)
from app.domain.marketdata import Candle, LastPrice, Timeframe
from app.services.market_data import MarketDataService


def _candle(ts: str, value: str) -> Candle:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return Candle(
        figi="BBG004730N88",
        timeframe=Timeframe.MIN_1,
        timestamp=dt,
        open=Decimal(value),
        high=Decimal(value),
        low=Decimal(value),
        close=Decimal(value),
        volume=1,
    )


class FakeBroker:
    def __init__(
        self, candles: list[Candle] | None = None, candles_error: Exception | None = None
    ) -> None:
        self._candles = candles or []
        self._candles_error = candles_error
        self.candle_calls: list[tuple] = []

    async def get_candles(self, figi, timeframe, from_, to, limit=None):
        self.candle_calls.append((figi, timeframe, from_, to))
        if self._candles_error:
            raise self._candles_error
        return [c for c in self._candles if from_ <= c.timestamp <= to]

    async def get_last_price(self, figi: str) -> LastPrice:
        return LastPrice(
            figi=figi,
            price=Decimal("300.5"),
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            ticker="SBER",
        )


@pytest.mark.asyncio
async def test_last_price_normalized() -> None:
    service = MarketDataService(FakeBroker())
    price = await service.get_last_price("BBG004730N88")
    assert price.figi == "BBG004730N88"
    assert price.price == Decimal("300.5")
    assert price.timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_candles_sorted_and_deduplicated() -> None:
    # Boundary candle at Jan2 appears in both chunks; input is unsorted.
    candles = [
        _candle("2025-01-01T00:00:00Z", "1"),
        _candle("2025-01-03T00:00:00Z", "3"),
        _candle("2025-01-02T00:00:00Z", "2"),
    ]
    broker = FakeBroker(candles=candles)
    service = MarketDataService(broker)

    result = await service.get_candles(
        "BBG004730N88",
        Timeframe.MIN_1,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 3, tzinfo=UTC),
    )
    # 2-day range at 1m chunk (1 day) -> two requests.
    assert len(broker.candle_calls) == 2
    stamps = [c.timestamp for c in result]
    assert stamps == sorted(stamps)
    # deduplicated: 3 unique candles, no duplicate boundary.
    assert len(result) == 3
    assert {s.isoformat() for s in stamps} == {
        "2025-01-01T00:00:00+00:00",
        "2025-01-02T00:00:00+00:00",
        "2025-01-03T00:00:00+00:00",
    }
    # timeframe and figi preserved on each candle.
    for c in result:
        assert c.figi == "BBG004730N88"
        assert c.timeframe == Timeframe.MIN_1


@pytest.mark.asyncio
async def test_candles_timeframe_passed_to_broker() -> None:
    broker = FakeBroker()
    service = MarketDataService(broker)
    await service.get_candles(
        "F",
        Timeframe.HOUR_1,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
    )
    assert broker.candle_calls[0][1] == Timeframe.HOUR_1


@pytest.mark.asyncio
async def test_invalid_date_range_raises() -> None:
    service = MarketDataService(FakeBroker())
    with pytest.raises(InvalidRequestError):
        await service.get_candles(
            "F",
            Timeframe.HOUR_1,
            datetime(2025, 1, 2, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_unknown_instrument_maps_to_404() -> None:
    broker = FakeBroker(candles_error=ResourceNotFoundError("not found"))
    service = MarketDataService(broker)
    with pytest.raises(InstrumentNotFoundError):
        await service.get_candles(
            "F",
            Timeframe.HOUR_1,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
        )
