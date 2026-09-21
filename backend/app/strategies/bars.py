"""Bar / BarSeries / Snapshot for the Strategy Engine.

The engine is broker-agnostic: it consumes normalized bar series keyed by
timeframe (produced by the Market Data layer), never T-Invest objects. Values are
kept as floats here because they feed indicator computation (analysis); the
engine's financial *outputs* stay on Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.marketdata import Timeframe


@dataclass(frozen=True)
class Bar:
    """A single OHLCV bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    # False for a forming (not-yet-closed) bar; used by the AT_BAR_CLOSE method.
    is_complete: bool = True


@dataclass
class BarSeries:
    """A chronological, normalized bar series for one timeframe."""

    timeframe: Timeframe
    bars: list[Bar] = field(default_factory=list)

    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    def highs(self) -> list[float]:
        return [b.high for b in self.bars]

    def lows(self) -> list[float]:
        return [b.low for b in self.bars]

    def volumes(self) -> list[float]:
        return [b.volume for b in self.bars]

    def opens(self) -> list[float]:
        return [b.open for b in self.bars]

    def attr(self, name: str) -> list[float]:
        values = {
            "open": self.opens(),
            "high": self.highs(),
            "low": self.lows(),
            "close": self.closes(),
            "volume": self.volumes(),
        }
        return values[name]

    def __len__(self) -> int:
        return len(self.bars)


@dataclass
class Snapshot:
    """Bar series keyed by timeframe handed to the Strategy Engine."""

    series: dict[Timeframe, BarSeries] = field(default_factory=dict)

    def get(self, timeframe: Timeframe) -> BarSeries | None:
        return self.series.get(timeframe)
