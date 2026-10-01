# Veles-MOEX — Independent Review: MVP-6.14

## Verdict (round 1)

**ACCEPT**

Accepted implementation: `c1558bde659df94a42689a8f658650e7b254acd3` (`agent/review/mvp-6.14`, pushed, in sync with origin)
Base: `master @ bb52d368c82ae5e32ff8fa3cae41ba5439191321` (merge-base verified)
Report: `.agent/REPORT-MVP-6.14.md` (`agent/control @ 1134426`)
Reviewer: Claude (independent review), 2026-10-01

## Independent re-run (clean environment, Python 3.12)

| Check | Result |
|---|---|
| `pytest` (full) | **499 passed, 1 skipped** — matches the REPORT |
| `ruff check app tests scripts` | All checks passed |
| `alembic heads` | single head `0005_deal_continuation` (no migration) |
| push rule | review branch and REPORT pushed; the REPORT cites the pushed SHA ✓ |

## Contract check

- **N2**: `MarketSnapshot.last_trade_at` is a separate field (`timestamp` keeps its MVP-6.10 meaning). `NoTradesInWindow(MarketDataUnavailable)` carries `last_trade_at` + `window_start`, so every existing `MarketDataUnavailable` handler still works.
- **N1**: `_proven_no_trade_bar()` checks the target range `[bar_start(boundary − 1 s), boundary)`. Any candle in the range (even incomplete) disproves the skip. It is proven only by a candle `start ≥ boundary` or by `last_trade_at < bar start`. `_proven_no_trade_window()` requires a known `last_trade_at < window_start`. A skip concludes the boundary without a cycle and leaves the failure counter untouched; `last_skip_reason` is exposed in `GET /api/bots/{id}` and reset with the per-bot state on a state change.
- **N3**: `AT_BAR_CLOSE` normal path and `PER_MINUTE` empty window are covered; the S6 deferred path is unchanged (existing MVP-6.13 tests green).

## Reviewer probes on `c1558bd` (M5, 30 minutes, trading available)

| Scenario | Result |
|---|---|
| Thin instrument: no candles after `T0−10m`, last trade `T0−8m` | **0 failures, 0 cycles**, every bar skipped, `last_skip_reason` set ✓ |
| Lagging feed: last trade 20 s ago inside each bar, candles not delivered | bot → **ERROR after 3 ticks** (lag still detected) ✓ |

## Follow-ups (non-blocking)

1. `PER_MINUTE` with a successful but stale snapshot (old candles, no exception) still runs the cycle on the old data, as before 6.14 (pre-existing semantics; out of scope).
2. Remaining candidates from `PROJECT_STATE.md`: snapshot by bar count across session gaps; `HOUR_4`/`WEEK_1`/`MONTH_1` candle times; exit modes; recovery TP churn; `FILLED -> UNKNOWN` cancel error.
3. Publication: PR `agent/review/mvp-6.14` → `master` (merge commit pinned to `c1558bd`); mirror the MVP-6.14 records; close Issue #11.
