"""Indicator library for the Strategy Engine.

Pure functions operating on normalized bar series (broker-agnostic). Outputs are
lists of ``float | None`` (``None`` where the indicator is undefined for the
window). The library is extensible: adding an indicator only requires a new
function plus a registry entry; the Strategy Engine does not change.
"""

from __future__ import annotations

from app.strategies.bars import BarSeries


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


def rsi(values, period=14):
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


def atr(high, low, close, period=14):
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


def cci(high, low, close, period=20):
    n = len(close)
    out = [None] * n
    tp = [(h + lo + c) / 3.0 for h, lo, c in zip(high, low, close, strict=False)]
    for i in range(period - 1, n):
        window = tp[i - period + 1 : i + 1]
        mean = sum(window) / period
        md = sum(abs(v - mean) for v in window) / period
        out[i] = (tp[i] - mean) / (0.015 * md) if md else 0.0
    return out


def williams_r(high, low, close, period=14):
    n = len(high)
    out = [None] * n
    for i in range(period - 1, n):
        hh = max(high[i - period + 1 : i + 1])
        ll = min(low[i - period + 1 : i + 1])
        out[i] = -100.0 * (hh - close[i]) / (hh - ll) if hh != ll else -50.0
    return out


def cmo(values, period=14):
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


def mfi(high, low, close, volume, period=14):
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


def stochastic(high, low, close, period=14, k_smooth=3, d_smooth=3):
    n = len(close)
    k = [None] * n
    for i in range(period - 1, n):
        hh = max(high[i - period + 1 : i + 1])
        ll = min(low[i - period + 1 : i + 1])
        k[i] = 100.0 * (close[i] - ll) / (hh - ll) if hh != ll else 50.0
    k_s = sma(k, k_smooth)
    d_s = sma(k_s, d_smooth)
    return k_s, d_s


def adx(high, low, close, period=14):
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


def indicator_series(
    name: str, series: BarSeries, period: int | None, series_name: str, params: dict
) -> list[float]:
    """Compute the requested output series for a named indicator."""
    name_u = name.upper()
    closes = series.closes()
    if name_u == "SMA":
        return sma(closes, period or 20)
    if name_u == "EMA":
        return ema(closes, period or 9)
    if name_u == "RSI":
        return rsi(closes, period or 14)
    if name_u == "MACD":
        fast = int(params.get("fast", 12))
        slow = int(params.get("slow", 26))
        signal = int(params.get("signal", 9))
        m, s, h = macd(closes, fast, slow, signal)
        return {"macd": m, "signal": s, "histogram": h}.get(series_name, m)
    if name_u == "BOLLINGER":
        k = float(params.get("k", 2.0))
        mid, up, low = bollinger(closes, period or 20, k)
        return {"middle": mid, "upper": up, "lower": low}.get(series_name, mid)
    if name_u == "ATR":
        return atr(series.highs(), series.lows(), closes, period or 14)
    if name_u == "CCI":
        return cci(series.highs(), series.lows(), closes, period or 20)
    if name_u in ("WILLIAMS_R", "WILLIAMS%R"):
        return williams_r(series.highs(), series.lows(), closes, period or 14)
    if name_u == "CMO":
        return cmo(closes, period or 14)
    if name_u == "MFI":
        return mfi(series.highs(), series.lows(), closes, series.volumes(), period or 14)
    if name_u == "STOCHASTIC":
        ks = int(params.get("k_smooth", 3))
        ds = int(params.get("d_smooth", 3))
        k, d = stochastic(series.highs(), series.lows(), closes, period or 14, ks, ds)
        return {"k": k, "d": d}.get(series_name, k)
    if name_u == "ADX":
        adx_line, pdi, mdi = adx(series.highs(), series.lows(), closes, period or 14)
        return {"adx": adx_line, "plus_di": pdi, "minus_di": mdi}.get(series_name, adx_line)
    raise ValueError(f"Unknown indicator: {name}")
