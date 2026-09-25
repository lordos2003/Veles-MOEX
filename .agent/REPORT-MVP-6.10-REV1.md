# Veles-MOEX — REPORT: MVP-6.10 (Revision 1 — review correction)

## Task / MVP

MVP-6.10 — Live Market Snapshot & Per-Bot Timeframe. This is the **revision**
report responding to the independent review
`6a2ed62 review: reject MVP-6.10 pending indicator warmup correction`
(`.agent/REVIEW-MVP-6.10.md`, verdict REJECTED, single blocking finding:
self-defined indicator warmup rules).

## Implementation branch / commits

- Branch: `agent/review/mvp-6.10` (base `master @ cdc1029`).
- Original implementation commit: `4c4e8fa` (unchanged).
- **Revision commit: `27d469c` — "fix: remove self-defined indicator warmup
  from snapshot lookback (MVP-6.10 review correction)"** (published to
  `origin/agent/review/mvp-6.10`).
- Review branch HEAD: `27d469c`.
- `master` NOT modified; no merge/rebase.

## Veles documentation consulted (per AGENTS.md Veles compatibility rule)

- `Veles Help Center — engineering reference.md` (Filter engine, Flexible
  indicators, Indicator catalog, indicator-specific principles).
- The documentation defines flexible indicators through **explicit user
  parameters** (custom periods/lengths, timeframe, method, shift) and does
  **not** define a universal warmup/history/lookback contract. No per-indicator
  required-history rule is established by the documentation.

## Exact changes (revision commit `27d469c`)

### 1. `backend/app/strategies/config.py`

- **Removed** the self-defined warmup table `_INDICATOR_WARMUP_BARS`
  (SMA=20, EMA=9, RSI=14, BOLLINGER=20, ATR=14, CCI=20, WILLIAMS_R=14,
  CMO=14, MFI=14, STOCHASTIC=14, ADX=28) — these were implementation
  assumptions about Veles indicator history requirements, not established by
  the Veles documentation.
- **Removed** the MACD `slow + signal` default-parameter formula (26/9
  defaults were implementation defaults, not a documented contract).
- **Refactored** `_argument_required_bars()` so the required history is
  derived **only from explicit strategy-contract values**:
  - `ConstantValue` -> 0;
  - `CandleSpec` -> explicit `shift` + 1;
  - `IndicatorSpec` -> explicit `period` (when set) + explicit `shift` + 1
    (+1 is the previous bar read by the project's crossing operators — a
    documented property of the project's filter engine, not an indicator
    warmup).
  - **No default-period substitution, no indicator-specific warmup
    inference, no warmup table.** An argument without an explicit period
    contributes only its shift.
- `required_bars()` keeps its name and contract (entry groups + SIGNAL-mode
  grid signal groups; always >= 2) but no longer invents indicator semantics:
  it computes the market data required by the **explicitly defined,
  already-supported** strategy contract.
- Behavior when fetched history is insufficient for an indicator (e.g. an
  argument without an explicit period): the strategy engine's **existing**
  insufficient-data semantics apply unchanged — an undefined indicator value
  evaluates the condition as False -> no signal -> no order. No new
  evaluation semantics are introduced; the indicator library
  (`app/strategies/indicators.py`) is untouched (scope discipline).

### 2. `backend/tests/test_mvp610_market_snapshot.py`

- Updated `test_snapshot_request_uses_required_bars_from_config`: the
  expected 21 bars now come from the **explicit** SMA period (20) + 1
  (previous bar), not from an inferred warmup.
- Added `test_required_bars_does_not_infer_indicator_warmup`: an RSI argument
  **without** an explicit period contributes only shift+1 (required == 2),
  i.e. no inferred 14-bar warmup.
- Added `test_required_bars_uses_explicit_period_and_shift_only`: explicit
  EMA `period=9`, `shift=3` -> 9 + 3 + 1 == 13.

### 3. `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`

- Section 28 "Per-bot timeframe" rewritten for `required_bars`: only explicit
  indicator periods and explicit shifts; the Veles documentation does not
  define a universal warmup contract, so no warmup is inferred; the
  per-indicator warmup specification is a documented boundary pending the
  Veles specification.
- Section 28 "Testing" updated with the new no-inferred-warmup coverage.

## What did NOT change (accepted parts of `4c4e8fa`, unchanged)

- broker-neutral `MarketSnapshot` boundary (`app/domain/marketdata.py`);
- `MarketDataService.get_snapshot` (real broker data, `Decimal` prices,
  UTC-aware timestamps, `MarketDataUnavailable` on missing/invalid data);
- explicit per-bot timeframe (`StrategyConfig.timeframe`,
  `TimeframeNotConfigured`, `StrategyLoadError` on invalid);
- `BotRuntime.market_context_provider` and `execute_strategy()`;
- `TradingEngine` live gates (missing timeframe -> explicit cycle failure;
  snapshot without the bot-timeframe series -> no live intents);
- MVP-6.9 position-state gate (unchanged, preserved);
- Backtest isolation (BacktestBroker/BacktestConfig/DCA-Grid/Filter semantics
  untouched);
- no T-Invest order submission; broker mapping stays in `TInvestAdapter`.

## Validation results

- `pytest`: **371 passed, 1 skipped** (was 369 passed, 1 skipped before the
  revision; +2 new no-inferred-warmup tests; the single skip is the opt-in
  live sandbox integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `npm run build`: **✓ built** (152.28 kB js / 7.72 kB css).
- Actual diff inspected: the revision touches only
  `backend/app/strategies/config.py`,
  `backend/tests/test_mvp610_market_snapshot.py` and
  `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`; no Veles Filter/Signal,
  DCA/Grid, Backtest, PositionManager, broker-neutral, Decimal, UTC or
  T-Invest read-only semantics changed.

## Multi-timeframe filter observation (review, non-blocking)

Addressed as required: the MVP **does not claim full support** for Veles
filters whose arguments use intervals other than the bot's configured
timeframe. The live snapshot provides only the bot-timeframe series; a filter
argument with a different timeframe receives **no** series and is evaluated
as undefined (condition False -> no signal) — it is **never silently
evaluated against the bot timeframe** (no series substitution). Fetching
additional per-argument timeframes is a follow-up requiring the Veles
multi-interval specification (documented limitation, unchanged from the
original report).

## Known limitations

- An argument without an explicit period may receive less history than a
  particular indicator implementation internally "warms up" over; per the
  existing filter semantics this yields an undefined value -> condition
  False -> no signal (no order). No warmup rule is invented to widen the
  fetch.
- The live strategy cycle trigger (scheduling) is not part of this MVP.
- No actual live order submission (T-Invest read-only), per the MVP scope.

## Documentation / specification gaps

- The Veles documentation does not define per-indicator warmup/history
  requirements. Per the AGENTS.md Veles compatibility rule, this project
  stops at that boundary: no rule is invented, no conventional default is
  chosen silently; the boundary is documented here and in TASK-09 §28. If an
  exact per-indicator warmup contract is required, the Veles specification
  must be established (or clarified) first.

## Git state

- `agent/review/mvp-6.10` -> `27d469c` (published).
- `master` unchanged (revision work performed strictly on the review
  branch); no merge/rebase; working tree clean.
- `agent/control` updated with this report only.
