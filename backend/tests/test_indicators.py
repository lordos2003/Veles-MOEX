"""Deterministic indicator library tests (Strategy Engine MVP-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.marketdata import Timeframe
from app.strategies.bars import Bar, BarSeries
from app.strategies.indicators import (
    ema,
    indicator_series,
    macd,
    rsi,
    sma,
)

UTC = UTC
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
INDICATORS = [
    "RSI",
    "SMA",
    "EMA",
    "MACD",
    "BOLLINGER",
    "ATR",
    "CCI",
    "WILLIAMS_R",
    "CMO",
    "MFI",
    "STOCHASTIC",
    "ADX",
]


def _series(closes: list[float]) -> BarSeries:
    bars = []
    for i, c in enumerate(closes):
        bars.append(
            Bar(
                timestamp=T0 + timedelta(minutes=i),
                open=c,
                high=c * 1.01,
                low=c * 0.99,
                close=c,
                volume=1000.0,
                is_complete=True,
            )
        )
    return BarSeries(timeframe=Timeframe.MIN_5, bars=bars)


def test_sma_matches_hand_computation() -> None:
    assert sma([1, 2, 3, 4, 5], 2) == [None, 1.5, 2.5, 3.5, 4.5]


def test_ema_seeds_from_first_value() -> None:
    out = ema([1.0, 2.0, 3.0], 2)
    # k = 2/3: 1.0 -> 1.0 + 2/3*(2-1)=1.6667 -> 1.6667 + 2/3*(3-1.6667)=2.5556
    assert out[0] == pytest.approx(1.0)
    assert out[1] == pytest.approx(1.0 + (2.0 / 3.0) * (2.0 - 1.0))
    assert out[2] == pytest.approx(out[1] + (2.0 / 3.0) * (3.0 - out[1]))


def test_rsi_strictly_rising_is_100() -> None:
    out = rsi([1.0, 2.0, 3.0, 4.0, 5.0], 2)
    assert out[2] == pytest.approx(100.0)


def test_macd_returns_three_series_same_length() -> None:
    closes = [float(i) for i in range(1, 40)]
    macd_line, signal_line, hist = macd(closes, 5, 10, 3)
    assert len(macd_line) == len(closes)
    assert len(signal_line) == len(closes)
    assert len(hist) == len(closes)
    # macd line = fast EMA - slow EMA where defined.
    assert macd_line[-1] == pytest.approx(ema(closes, 5)[-1] - ema(closes, 10)[-1])


def test_all_indicators_return_full_series() -> None:
    series = _series([float(i) for i in range(1, 61)])
    n = len(series.bars)
    for name in INDICATORS:
        out = indicator_series(name, series, period=14, series_name="value", params={})
        assert len(out) == n, name
        # some indicator must hold a defined value at the final bar.
        assert out[-1] is not None, name


def test_indicator_output_selector() -> None:
    series = _series([float(i) for i in range(1, 61)])
    hist = indicator_series(
        "MACD",
        series,
        period=14,
        series_name="histogram",
        params={"fast": 4, "slow": 8, "signal": 3},
    )
    assert len(hist) == len(series.bars)
    upper = indicator_series("BOLLINGER", series, period=14, series_name="upper", params={})
    assert len(upper) == len(series.bars)
    kline = indicator_series("STOCHASTIC", series, period=14, series_name="k", params={})
    assert len(kline) == len(series.bars)


def test_unknown_indicator_raises() -> None:
    series = _series([float(i) for i in range(1, 30)])
    with pytest.raises(ValueError):
        indicator_series("NOPE", series, period=14, series_name="value", params={})
