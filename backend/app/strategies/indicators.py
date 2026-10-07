"""Indicator library for the Strategy Engine.

Pure functions operating on normalized bar series (broker-agnostic). Outputs are
lists of ``float | None`` (``None`` where the indicator is undefined for the
window). The library is extensible: adding an indicator only requires a new
function plus a registry entry; the Strategy Engine does not change.

Default values (MVP-7.2 I1/I4): every period and parameter the calculation
consumes is declared explicitly in |INDICATOR_CATALOG| with a ``default`` and a
``default_source`` (``veles`` = documented by Veles, ``project`` = owner-
approved project choice). The calculation functions take required parameters
only: a missing period/parameter raises an explicit error through
``validate_spec_args`` / ``indicator_series`` instead of a hidden fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.strategies.bars import BarSeries

DefaultSource = Literal["veles", "project"]


def sma(values: list[float], period: int) -> list[float]:
    n = len(values)
    out: list[float | None] = [None] * n
    for i in range(n):
        window = values[max(0, i - period + 1) : i + 1]
        defined = [v for v in window if v is not None]
        if len(defined) == period:
            out[i] = sum(defined) / period
    return out


def ema(values: list[float], period: int) -> list[float]:
    out: list[float | None] = [None] * len(values)
    if not values:
        return out
    k = 2.0 / (period + 1)
    prev: float | None = None
    for i, value in enumerate(values):
        prev = value if prev is None else prev + k * (value - prev)
        out[i] = prev
    return out


def macd(values, fast, slow, signal):
    fast_e = ema(values, fast)
    slow_e = ema(values, slow)
    macd_line = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(fast_e, slow_e, strict=False)
    ]
    valid = [v for v in macd_line if v is not None]
    start = len(macd_line) - len(valid)
    signal_e = ema(valid, signal)
    signal_line = [None] * start + signal_e
    hist = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(macd_line, signal_line, strict=False)
    ]
    return macd_line, signal_line, hist


def bollinger(values, period, k):
    n = len(values)
    middle = sma(values, period)
    upper = [None] * n
    lower = [None] * n
    for i in range(period - 1, n):
        window = values[i - period + 1 : i + 1]
        mean = middle[i]
        std = (sum((v - mean) ** 2 for v in window) / period) ** 0.5
        upper[i] = mean + k * std
        lower[i] = mean - k * std
    return middle, upper, lower


def rsi(values, period):
    n = len(values)
    out = [None] * n
    if n < period + 1:
        return out
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    def _rs(g, loss):
        if loss == 0.0:
            return 100.0 if g != 0.0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / loss)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rs(avg_gain, avg_loss)
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rs(avg_gain, avg_loss)
    return out


def atr(high, low, close, period):
    n = len(high)
    out = [None] * n
    if n < period + 1:
        return out
    trs: list[float] = []
    for i in range(1, n):
        trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    avg = sum(trs[:period]) / period
    out[period] = avg
    for i in range(period, n - 1):
        avg = (avg * (period - 1) + trs[i]) / period
        out[i + 1] = avg
    return out


def cci(high, low, close, period):
    n = len(close)
    out = [None] * n
    tp = [(h + lo + c) / 3.0 for h, lo, c in zip(high, low, close, strict=False)]
    for i in range(period - 1, n):
        window = tp[i - period + 1 : i + 1]
        mean = sum(window) / period
        md = sum(abs(v - mean) for v in window) / period
        out[i] = (tp[i] - mean) / (0.015 * md) if md else 0.0
    return out


def williams_r(high, low, close, period):
    n = len(high)
    out = [None] * n
    for i in range(period - 1, n):
        hh = max(high[i - period + 1 : i + 1])
        ll = min(low[i - period + 1 : i + 1])
        out[i] = -100.0 * (hh - close[i]) / (hh - ll) if hh != ll else -50.0
    return out


def cmo(values, period):
    n = len(values)
    out = [None] * n
    for i in range(period, n):
        ups = sums = 0.0
        for j in range(i - period + 1, i + 1):
            delta = values[j] - values[j - 1]
            if delta >= 0:
                ups += delta
            else:
                sums += -delta
        denom = ups + sums
        out[i] = 100.0 * (ups - sums) / denom if denom else 0.0
    return out


def mfi(high, low, close, volume, period):
    n = len(close)
    out = [None] * n
    typical = [(h + lo + c) / 3.0 for h, lo, c in zip(high, low, close, strict=False)]
    raw = [typical[i] * volume[i] for i in range(n)]
    for i in range(period, n):
        pos = neg = 0.0
        for j in range(i - period + 1, i + 1):
            if typical[j] > typical[j - 1]:
                pos += raw[j]
            elif typical[j] < typical[j - 1]:
                neg += raw[j]
        if neg == 0.0:
            out[i] = 100.0 if pos else 50.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + pos / neg)
    return out


def stochastic(high, low, close, period, k_smooth, d_smooth):
    n = len(close)
    k = [None] * n
    for i in range(period - 1, n):
        hh = max(high[i - period + 1 : i + 1])
        ll = min(low[i - period + 1 : i + 1])
        k[i] = 100.0 * (close[i] - ll) / (hh - ll) if hh != ll else 50.0
    k_s = sma(k, k_smooth)
    d_s = sma(k_s, d_smooth)
    return k_s, d_s


def adx(high, low, close, period):
    n = len(high)
    pdi = [None] * n
    mdi = [None] * n
    adx_line = [None] * n
    if n < 2 * period:
        return adx_line, pdi, mdi

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr: list[float] = []
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))

    w_pdm = _wildered(plus_dm, period)
    w_mdm = _wildered(minus_dm, period)
    w_tr = _wildered(tr, period)

    dx_seq: list[tuple[int, float]] = []
    for b in range(period, n):
        d = b - 1
        if d >= len(w_tr):
            break
        a = w_tr[d]
        p = w_pdm[d]
        m = w_mdm[d]
        p_di = 100.0 * p / a if a else 0.0
        m_di = 100.0 * m / a if a else 0.0
        pdi[b] = p_di
        mdi[b] = m_di
        dx = 100.0 * abs(p_di - m_di) / (p_di + m_di) if (p_di + m_di) else 0.0
        dx_seq.append((b, dx))

    if len(dx_seq) >= period:
        seq = [dx for _, dx in dx_seq]
        w_dx = _wildered(seq, period)
        for idx, (b, _) in enumerate(dx_seq):
            if idx >= period - 1:
                adx_line[b] = w_dx[idx]
    return adx_line, pdi, mdi


def _wildered(raw: list[float], period: int) -> list[float]:
    """Wilder smoothing over a raw delta series."""
    out = [0.0] * len(raw)
    if len(raw) < period:
        return out
    acc = sum(raw[:period])
    out[period - 1] = acc
    for i in range(period, len(raw)):
        acc = acc - (acc / period) + raw[i]
        out[i] = acc
    return out


@dataclass(frozen=True)
class IndicatorParamDef:
    """One configurable parameter of an indicator (MVP-7.1 U3, MVP-7.2 I1/I4).

    ``type`` is ``"int"`` or ``"float"``. ``required`` is engine-level: every
    parameter the calculation consumes is required (I4) — the old hidden
    fallbacks (``params.get("fast", 12)`` ...) are gone. ``default`` and
    ``default_source`` are the single source of truth for the form pre-fill
    (I3): ``veles`` when the value is documented by Veles, ``project`` when it
    is an owner-approved project choice.
    """

    name: str
    type: str
    required: bool
    default: int | float
    default_source: DefaultSource


@dataclass(frozen=True)
class IndicatorDef:
    """Catalog entry describing one indicator the engine can compute (U3).

    ``series`` is the tuple of output series recognizable by the engine (the
    ``IndicatorSpec.series`` selector); unknown series fall back to the first
    one. ``uses_*`` report which ``IndicatorSpec`` fields the calculation
    consumes (``period`` / ``method`` / ``series`` / ``params``).
    ``period_default`` / ``period_default_source`` declare the explicit default
    for ``IndicatorSpec.period`` (None when the indicator does not use period).
    """

    name: str
    series: tuple[str, ...]
    params: tuple[IndicatorParamDef, ...]
    uses_period: bool
    uses_method: bool
    uses_series: bool
    uses_params: bool
    period_default: int | None = None
    period_default_source: DefaultSource | None = None


def _param(name: str, type_: str, default: int | float, source: DefaultSource) -> IndicatorParamDef:
    """Required catalog parameter (I4): the calculation has no fallback."""
    return IndicatorParamDef(
        name=name, type=type_, required=True, default=default, default_source=source
    )


Compute = Callable[[BarSeries, int, str, dict], list[float]]


def _macd_compute(
    series: BarSeries, period: int, series_name: str, params: dict
) -> list[float]:
    fast = int(params["fast"])
    slow = int(params["slow"])
    signal = int(params["signal"])
    m, s, h = macd(series.closes(), fast, slow, signal)
    return {"macd": m, "signal": s, "histogram": h}.get(series_name, m)


def _bollinger_compute(
    series: BarSeries, period: int, series_name: str, params: dict
) -> list[float]:
    mid, up, low = bollinger(series.closes(), period, float(params["k"]))
    return {"middle": mid, "upper": up, "lower": low}.get(series_name, mid)


def _stochastic_compute(
    series: BarSeries, period: int, series_name: str, params: dict
) -> list[float]:
    k, d = stochastic(
        series.highs(),
        series.lows(),
        series.closes(),
        period,
        int(params["k_smooth"]),
        int(params["d_smooth"]),
    )
    return {"k": k, "d": d}.get(series_name, k)


def _adx_compute(
    series: BarSeries, period: int, series_name: str, params: dict
) -> list[float]:
    adx_line, pdi, mdi = adx(series.highs(), series.lows(), series.closes(), period)
    return {"adx": adx_line, "plus_di": pdi, "minus_di": mdi}.get(series_name, adx_line)


# Single dispatch source for indicator_series. The catalog (INDICATOR_CATALOG)
# and the calculation cannot diverge: the test asserts both are driven by the
# same keys (backend/tests/test_mvp71_api.py).
_COMPUTE: dict[str, Compute] = {
    "SMA": lambda s, p, sn, prm: sma(s.closes(), p),
    "EMA": lambda s, p, sn, prm: ema(s.closes(), p),
    "RSI": lambda s, p, sn, prm: rsi(s.closes(), p),
    "MACD": _macd_compute,
    "BOLLINGER": _bollinger_compute,
    "ATR": lambda s, p, sn, prm: atr(s.highs(), s.lows(), s.closes(), p),
    "CCI": lambda s, p, sn, prm: cci(s.highs(), s.lows(), s.closes(), p),
    "WILLIAMS_R": lambda s, p, sn, prm: williams_r(s.highs(), s.lows(), s.closes(), p),
    "CMO": lambda s, p, sn, prm: cmo(s.closes(), p),
    "MFI": lambda s, p, sn, prm: mfi(s.highs(), s.lows(), s.closes(), s.volumes(), p),
    "STOCHASTIC": _stochastic_compute,
    "ADX": _adx_compute,
}
# Parser alias kept for existing saved configs (the indicator_series if-chain
# historically accepted both spellings).
_COMPUTE["WILLIAMS%R"] = _COMPUTE["WILLIAMS_R"]


def _catalog_entry(name: str) -> IndicatorDef | None:
    key = name.upper()
    return _CATALOG_BY_NAME.get(_ALIASES.get(key, key))


def validate_spec_args(name: str, period: int | None, params: dict) -> None:
    """Catalog-driven validation of one indicator spec (I4).

    Raises ``ValueError`` with a Russian user-facing message naming the
    indicator and the missing period/parameter — no hidden fallback is applied.
    ``StrategyConfig`` validation and the calculation engine both call this.
    """
    entry = _catalog_entry(name)
    if entry is None:
        # Unknown names are rejected by indicator_series at calculation time.
        return
    if entry.uses_period and period is None:
        raise ValueError(f"Индикатор {entry.name}: укажите параметр «период».")
    for param in entry.params:
        if param.required and (param.name not in params or params[param.name] is None):
            raise ValueError(f"Индикатор {entry.name}: укажите параметр «{param.name}».")


INDICATOR_CATALOG: tuple[IndicatorDef, ...] = (
    IndicatorDef(
        name="SMA",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=20,
        period_default_source="project",
    ),
    IndicatorDef(
        name="EMA",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=9,
        period_default_source="project",
    ),
    IndicatorDef(
        name="RSI",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=14,
        period_default_source="veles",
    ),
    IndicatorDef(
        name="MACD",
        series=("macd", "signal", "histogram"),
        params=(
            _param("fast", "int", 12, "project"),
            _param("slow", "int", 26, "project"),
            _param("signal", "int", 9, "project"),
        ),
        uses_period=False,
        uses_method=False,
        uses_series=True,
        uses_params=True,
    ),
    IndicatorDef(
        name="BOLLINGER",
        series=("middle", "upper", "lower"),
        params=(_param("k", "float", 2.0, "veles"),),
        uses_period=True,
        uses_method=False,
        uses_series=True,
        uses_params=True,
        period_default=20,
        period_default_source="veles",
    ),
    IndicatorDef(
        name="ATR",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=14,
        period_default_source="project",
    ),
    IndicatorDef(
        name="CCI",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=20,
        period_default_source="project",
    ),
    IndicatorDef(
        name="WILLIAMS_R",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=14,
        period_default_source="project",
    ),
    IndicatorDef(
        name="CMO",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=14,
        period_default_source="project",
    ),
    IndicatorDef(
        name="MFI",
        series=("value",),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=False,
        uses_params=False,
        period_default=14,
        period_default_source="project",
    ),
    IndicatorDef(
        name="STOCHASTIC",
        series=("k", "d"),
        params=(
            _param("k_smooth", "int", 3, "project"),
            _param("d_smooth", "int", 3, "project"),
        ),
        uses_period=True,
        uses_method=False,
        uses_series=True,
        uses_params=True,
        period_default=14,
        period_default_source="project",
    ),
    IndicatorDef(
        name="ADX",
        series=("adx", "plus_di", "minus_di"),
        params=(),
        uses_period=True,
        uses_method=False,
        uses_series=True,
        uses_params=False,
        period_default=14,
        period_default_source="project",
    ),
)

_CATALOG_BY_NAME: dict[str, IndicatorDef] = {entry.name: entry for entry in INDICATOR_CATALOG}
_ALIASES: dict[str, str] = {"WILLIAMS%R": "WILLIAMS_R"}


def indicator_names() -> tuple[str, ...]:
    """Canonical indicator names the engine can compute (U3, no parser aliases)."""
    return tuple(sorted(name for name in _COMPUTE if name != "WILLIAMS%R"))


def indicator_series(
    name: str, series: BarSeries, period: int | None, series_name: str, params: dict
) -> list[float]:
    """Compute the requested output series for a named indicator.

    A period/parameter the calculation requires but the config does not declare
    raises an explicit ``ValueError`` (I4) — never a silent fallback.
    """
    compute = _COMPUTE.get(name.upper())
    if compute is None:
        raise ValueError(f"Unknown indicator: {name}")
    validate_spec_args(name, period, params)
    return compute(series, period if period is not None else 0, series_name, params)
