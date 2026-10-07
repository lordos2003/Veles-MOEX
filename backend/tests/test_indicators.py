"""Deterministic indicator library tests (Strategy Engine MVP-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.marketdata import Timeframe
from app.strategies.bars import Bar, BarSeries
from app.strategies.indicators import (
    INDICATOR_CATALOG,
    ema,
    indicator_series,
    macd,
    rsi,
    sma,
    validate_spec_args,
)

UTC = UTC
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


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
    for entry in INDICATOR_CATALOG:
        params = {param.name: param.default for param in entry.params}
        out = indicator_series(
            entry.name, series, period=entry.period_default, series_name="value", params=params
        )
        assert len(out) == n, entry.name
        # some indicator must hold a defined value at the final bar.
        assert out[-1] is not None, entry.name


def test_indicator_output_selector() -> None:
    series = _series([float(i) for i in range(1, 61)])
    hist = indicator_series(
        "MACD",
        series,
        period=None,
        series_name="histogram",
        params={"fast": 4, "slow": 8, "signal": 3},
    )
    assert len(hist) == len(series.bars)
    upper = indicator_series(
        "BOLLINGER", series, period=14, series_name="upper", params={"k": 2.0}
    )
    assert len(upper) == len(series.bars)
    kline = indicator_series(
        "STOCHASTIC",
        series,
        period=14,
        series_name="k",
        params={"k_smooth": 3, "d_smooth": 3},
    )
    assert len(kline) == len(series.bars)


def test_catalog_defaults_are_explicit_with_sources() -> None:
    """I1: every engine-used period/parameter has an explicit default and a
    source (``veles`` = documented by Veles, ``project`` = owner-approved
    project choice); no catalog entry relies on a hidden fallback."""
    by_name = {entry.name: entry for entry in INDICATOR_CATALOG}

    # Period defaults: required (non-None, int) exactly for uses_period entries.
    for entry in INDICATOR_CATALOG:
        if entry.uses_period:
            assert isinstance(entry.period_default, int), entry.name
            assert entry.period_default_source in ("veles", "project"), entry.name
        else:
            assert entry.period_default is None, entry.name
            assert entry.period_default_source is None, entry.name

    # Params: every catalog param is required by the calculation (I4) and
    # carries an explicit default + source.
    for entry in INDICATOR_CATALOG:
        for param in entry.params:
            assert param.required is True, f"{entry.name}.{param.name}"
            assert param.default is not None, f"{entry.name}.{param.name}"
            assert param.default_source in ("veles", "project"), f"{entry.name}.{param.name}"

    # The fixed I1 table (owner-approved MVP-7.2 values).
    assert by_name["RSI"].period_default == 14
    assert by_name["RSI"].period_default_source == "veles"
    assert by_name["BOLLINGER"].period_default == 20
    assert by_name["BOLLINGER"].period_default_source == "veles"
    macd_params = {p.name: (p.default, p.default_source) for p in by_name["MACD"].params}
    assert macd_params == {
        "fast": (12, "project"),
        "slow": (26, "project"),
        "signal": (9, "project"),
    }
    assert by_name["BOLLINGER"].params[0].default == 2.0
    assert by_name["BOLLINGER"].params[0].default_source == "veles"
    assert by_name["SMA"].period_default == 20 and by_name["SMA"].period_default_source == "project"
    assert by_name["EMA"].period_default == 9 and by_name["EMA"].period_default_source == "project"
    assert by_name["ATR"].period_default == 14 and by_name["ATR"].period_default_source == "project"
    assert by_name["CCI"].period_default == 20 and by_name["CCI"].period_default_source == "project"
    assert (
        by_name["WILLIAMS_R"].period_default == 14
        and by_name["WILLIAMS_R"].period_default_source == "project"
    )
    assert by_name["CMO"].period_default == 14 and by_name["CMO"].period_default_source == "project"
    assert by_name["MFI"].period_default == 14 and by_name["MFI"].period_default_source == "project"
    stoch_params = {p.name: p.default for p in by_name["STOCHASTIC"].params}
    assert stoch_params == {"k_smooth": 3, "d_smooth": 3}
    assert by_name["STOCHASTIC"].period_default == 14
    assert by_name["ADX"].period_default == 14 and by_name["ADX"].period_default_source == "project"


def test_missing_required_period_raises_explicit_error() -> None:
    series = _series([float(i) for i in range(1, 30)])
    with pytest.raises(ValueError, match=r"Индикатор RSI: укажите параметр «период»"):
        indicator_series("RSI", series, period=None, series_name="value", params={})


def test_missing_required_param_raises_explicit_error() -> None:
    series = _series([float(i) for i in range(1, 30)])
    with pytest.raises(ValueError, match=r"Индикатор MACD: укажите параметр «fast»"):
        indicator_series("MACD", series, period=None, series_name="macd", params={})
    with pytest.raises(ValueError, match=r"Индикатор BOLLINGER: укажите параметр «k»"):
        indicator_series("BOLLINGER", series, period=20, series_name="value", params={})


def test_zero_or_negative_period_raises_explicit_error() -> None:
    """B1: 0/negative integer periods pass the presence check but break the
    calculation (division by zero, silently empty series) — reject them with an
    explicit Russian message instead of crashing or yielding nothing."""
    series = _series([float(i) for i in range(1, 30)])
    for bad in (0, -5):
        with pytest.raises(
            ValueError,
            match=(
                r"Индикатор RSI: параметр «период» "
                r"должен быть целым числом не меньше 1"
            ),
        ):
            indicator_series("RSI", series, period=bad, series_name="value", params={})
    with pytest.raises(
        ValueError,
        match=(
            r"Индикатор SMA: параметр «период» "
            r"должен быть целым числом не меньше 1"
        ),
    ):
        indicator_series("SMA", series, period=-3, series_name="value", params={})
    with pytest.raises(
        ValueError,
        match=(
            r"Индикатор MACD: параметр «fast» "
            r"должен быть целым числом не меньше 1"
        ),
    ):
        indicator_series(
            "MACD",
            series,
            period=12,
            series_name="macd",
            params={"fast": 0, "slow": 26, "signal": 9},
        )


def test_validate_spec_args_rejects_zero_or_negative() -> None:
    """Same rule at the validation boundary (B1): integer params are >= 1,
    float params (k) are not bounded — the limit is arithmetical necessity,
    not Veles semantics."""
    for bad in (0, -5):
        with pytest.raises(ValueError, match=r"должен быть целым числом не меньше 1"):
            validate_spec_args("RSI", bad, {})
    with pytest.raises(ValueError, match=r"Индикатор MACD: параметр «fast»"):
        validate_spec_args("MACD", 12, {"fast": 0, "slow": 26, "signal": 9})
    validate_spec_args("BOLLINGER", 20, {"k": 0.0})
    # Numeric strings / whole floats stay accepted (old configs and JSON mode).
    validate_spec_args("SMA", "20", {})
    validate_spec_args("MACD", 12, {"fast": "12", "slow": 26, "signal": 9})
    validate_spec_args("MACD", 12, {"fast": 12.0, "slow": 26, "signal": 9})


# --- Regression: I1 defaults produce the pre-change numbers (no redefinition) ---
# Snapshot captured on the 80-bar fake series of test_mvp71_api before MVP-7.2.
N_BARS = 80
T0_REG = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _regression_series() -> BarSeries:
    bars = []
    for i in range(N_BARS):
        base = 100.0 + i * 0.1
        bars.append(
            Bar(
                timestamp=T0_REG + timedelta(minutes=i * 5),
                open=base,
                high=base + 1.0,
                low=base - 0.5,
                close=base + (0.2 if i % 2 == 0 else -0.2),
                volume=1000.0 + i,
            )
        )
    return BarSeries(timeframe=Timeframe.MIN_5, bars=bars)


# name.series -> (expected last value, checksum = round(sum(defined), 10), count)
_REG_SNAPSHOT: dict[str, tuple[float, float, int]] = {
    "SMA.value": (106.95, 6340.95, 61),
    "EMA.value": (107.47777779053834, 8286.8888888378, 80),
    "RSI.value": (60.73335202705429, 4099.7090894174, 66),
    "MACD.macd": (0.6877264904460105, 41.3367617285, 80),
    "MACD.signal": (0.6941541174047399, 38.5601452588, 80),
    "MACD.histogram": (-0.006427626958729338, 2.7766164696, 80),
    "BOLLINGER.middle": (106.95, 6340.95, 61),
    "BOLLINGER.upper": (108.1374342087038, 6415.3503527282, 61),
    "BOLLINGER.lower": (105.76256579129621, 6266.5496472718, 61),
    "ATR.value": (1.5, 99.0, 66),
    "CCI.value": (117.77777777777678, 7690.8462104488, 61),
    "WILLIAMS_R.value": (-42.85714285714278, -2400.0, 67),
    "CMO.value": (24.999999999999872, 1650.0, 66),
    "MFI.value": (49.98444814345553, 3302.1141986334, 66),
    "STOCHASTIC.k": (61.904761904761905, 4176.1904761905, 65),
    "STOCHASTIC.d": (63.49206349206347, 4049.2063492063, 63),
    "ADX.adx": (1400.0, 74200.0, 53),
    "ADX.plus_di": (6.666666666666694, 440.0, 66),
    "ADX.minus_di": (0.0, 0.0, 66),
}


def test_catalog_defaults_keep_prechange_numbers() -> None:
    """Explicit I1 defaults must reproduce the pre-MVP-7.2 values exactly:
    the default table is a *declaration* of existing behavior, not a change."""
    series = _regression_series()
    for entry in INDICATOR_CATALOG:
        params = {param.name: param.default for param in entry.params}
        for name in entry.series:
            out = indicator_series(
                entry.name, series, period=entry.period_default, series_name=name, params=params
            )
            expected_last, expected_checksum, expected_count = _REG_SNAPSHOT[f"{entry.name}.{name}"]
            defined = [v for v in out if v is not None]
            assert len(defined) == expected_count, f"{entry.name}.{name} count"
            assert out[-1] == pytest.approx(expected_last), f"{entry.name}.{name} last"
            checksum = round(sum(defined), 10)
            assert checksum == pytest.approx(expected_checksum), f"{entry.name}.{name} checksum"


def test_unknown_indicator_raises() -> None:
    series = _series([float(i) for i in range(1, 30)])
    with pytest.raises(ValueError):
        indicator_series("NOPE", series, period=14, series_name="value", params={})
