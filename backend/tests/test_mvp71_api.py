"""MVP-7.1 API acceptance tests (U2-U3).

Covers, with the same in-memory SQLite / httpx ASGI transport as
``test_mvp70_api.py``:

- U2 ``GET /api/runtime``: the mode comes from application settings
  (sandbox / live_trading_enabled / tinvest_configured), read-only;
- U3 ``GET /api/strategies/indicators``: the catalog is driven by the same
  registry as ``indicator_series`` — every catalog entry computes on fake bars
  for every listed series, and every engine name is present in the catalog
  (the catalog and the calculation cannot diverge).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_settings_dep
from app.core.config import Settings
from app.domain.marketdata import Timeframe
from app.main import app
from app.strategies.bars import Bar, BarSeries
from app.strategies.indicators import (
    INDICATOR_CATALOG,
    indicator_names,
    indicator_series,
)

N_BARS = 80
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _fake_series() -> BarSeries:
    """Deterministic OHLCV series long enough for every indicator period."""
    bars = []
    for i in range(N_BARS):
        base = 100.0 + i * 0.1
        bars.append(
            Bar(
                timestamp=T0 + timedelta(minutes=i * 5),
                open=base,
                high=base + 1.0,
                low=base - 0.5,
                close=base + (0.2 if i % 2 == 0 else -0.2),
                volume=1000.0 + i,
            )
        )
    return BarSeries(timeframe=Timeframe.MIN_5, bars=bars)


# --- U2: /api/runtime ------------------------------------------------------------


async def test_runtime_mode_comes_from_settings() -> None:
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        app.dependency_overrides[get_settings_dep] = lambda: Settings(
            tinvest_sandbox=True,
            live_trading_enabled=False,
            tinvest_token="token",
        )
        res = await http.get("/api/runtime")
        assert res.status_code == 200
        assert res.json() == {
            "sandbox": True,
            "live_trading_enabled": False,
            "tinvest_configured": True,
        }

        app.dependency_overrides[get_settings_dep] = lambda: Settings(
            tinvest_sandbox=False,
            live_trading_enabled=True,
            tinvest_token=None,
        )
        res = await http.get("/api/runtime")
        assert res.status_code == 200
        assert res.json() == {
            "sandbox": False,
            "live_trading_enabled": True,
            "tinvest_configured": False,
        }
    finally:
        app.dependency_overrides.pop(get_settings_dep, None)
        await http.aclose()


# --- U3: indicator catalog --------------------------------------------------------


@pytest.fixture
def fake_series() -> BarSeries:
    return _fake_series()


async def test_indicators_endpoint_lists_catalog(fake_series: BarSeries) -> None:
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        res = await http.get("/api/strategies/indicators")
        assert res.status_code == 200
        entries = res.json()
        by_name = {e["name"]: e for e in entries}

        # The catalog lists exactly the names the engine can compute.
        assert set(by_name) == set(indicator_names())
        for entry in entries:
            assert entry["series"]
            for param in entry["params"]:
                assert param["type"] in ("int", "float")
                assert isinstance(param["required"], bool)

        # MACD/BOLLINGER/STOCHASTIC/ADX expose output series; defaults are
        # never exposed (no "default" key anywhere in the catalog).
        assert by_name["MACD"]["series"] == ["macd", "signal", "histogram"]
        assert by_name["STOCHASTIC"]["series"] == ["k", "d"]
        for name in ("SMA", "EMA", "RSI", "ATR", "CCI", "WILLIAMS_R", "CMO", "MFI"):
            assert by_name[name]["series"] == ["value"]
            assert by_name[name]["params"] == []
        assert all("default" not in e for e in entries)
    finally:
        await http.aclose()


def test_every_catalog_entry_computes_on_fake_bars(fake_series: BarSeries) -> None:
    """Each catalog entry must be computable via ``indicator_series`` (U3)."""
    for entry in INDICATOR_CATALOG:
        params = {param.name: (11 if param.type == "int" else 2.5) for param in entry.params}
        for series_name in entry.series:
            result = indicator_series(
                entry.name, fake_series, period=20, series_name=series_name, params=dict(params)
            )
            assert len(result) == N_BARS, f"{entry.name}.{series_name} length mismatch"


def test_engine_names_and_parser_alias_stay_in_sync() -> None:
    """The registry the engine dispatches on equals the catalog names.

    The parser alias ``WILLIAMS%R`` (accepted by historical saved configs) is
    excluded from the canonical catalog but must still compute.
    """
    engine_names = set(indicator_names())
    catalog_names = {entry.name for entry in INDICATOR_CATALOG}
    assert engine_names == catalog_names


def test_unknown_indicator_fails_unchanged(fake_series: BarSeries) -> None:
    with pytest.raises(ValueError, match="Unknown indicator"):
        indicator_series("NOT_AN_INDICATOR", fake_series, period=20, series_name="value", params={})


def test_williams_percent_alias_computes(fake_series: BarSeries) -> None:
    result = indicator_series(
        "WILLIAMS%R", fake_series, period=14, series_name="value", params={}
    )
    assert len(result) == N_BARS
