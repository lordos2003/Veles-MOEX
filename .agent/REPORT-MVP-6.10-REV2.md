# Veles-MOEX — REPORT: MVP-6.10 (Revision 2 — review correction)

## Task / MVP

MVP-6.10 — Live Market Snapshot & Per-Bot Timeframe. This is the **revision 2**
report responding to the second independent review round: the refactored
`required_bars()` (revision 1) still carried self-defined Veles semantics —
`period + shift + 1`, a `+1` for crossing operators, and the claim that the
result is the "minimum history required by a Veles strategy" — none of which
is established by the official Veles documentation.

## Implementation branch / commits

- Branch: `agent/review/mvp-6.10` (base `master @ cdc1029`).
- Original implementation commit: `4c4e8fa` (unchanged).
- Revision 1 commit: `27d469c` (unchanged).
- **Revision 2 commit: `c7429fd` — "fix: replace inferred required_bars with
  explicit lookback_bars contract (MVP-6.10 review correction rev 2)"**
  (published to `origin/agent/review/mvp-6.10`).
- Review branch HEAD: `c7429fd`.
- `master` NOT modified; no merge/rebase.

## Veles documentation consulted (per AGENTS.md, fetched from master)

- `AGENTS.md` (current master `2280075`): Veles compatibility HARD RULE —
  do NOT invent warmup/history requirements, lookback rules, crossing
  semantics or other Veles-specific behavior; if the official documentation
  does not define a behavior, do not invent a rule, do not silently choose a
  conventional value, implement only the documented portion, stop at the
  boundary and document the limitation.
- `Veles Help Center — engineering reference.md`: flexible indicators are
  defined through explicit user parameters (custom periods/lengths,
  timeframe, method, shift). The documentation contains **no** universal
  warmup/history/lookback contract and **no** per-indicator required-history
  rule.

## Exact changes (revision 2 commit `c7429fd`)

### 1. `backend/app/strategies/config.py`

- **Removed entirely** the self-defined `required_bars()` algorithm and its
  helpers (`_argument_required_bars`, `_groups_required_bars`). No formula of
  the form `period + shift + 1` remains anywhere in the codebase; the
  crossing-operator `+1` and the "period establishes history size"
  interpretation are gone.
- **Added** `StrategyConfig.lookback_bars: int | None = Field(default=None,
  ge=1)` — a separate, **explicitly configurable** project-level parameter:
  the number of candle bars the live market snapshot fetches for the bot's
  timeframe. It is documented as a project contract, **not** a Veles
  indicator/warmup semantic:
  - `None` (missing) -> the live processing cycle fails explicitly
    (`LookbackNotConfigured`);
  - non-positive -> strategy configuration validation fails at load time
    (`StrategyLoadError`).
- Removed the now-unused filter-argument imports from this module.

### 2. `backend/app/trading/market_context.py`

- Added `LookbackNotConfigured` (explicit cycle failure, no lookback is
  inferred from indicator periods/shifts or any other Veles semantic; the
  live path never substitutes a default).
- `build_market_snapshot_context()` now reads the lookback exclusively from
  `StrategyConfig.lookback_bars` and passes it to
  `MarketDataService.get_snapshot(figi, timeframe, lookback_bars)`; missing
  lookback -> `LookbackNotConfigured` **before any broker request**.
- Module docstring updated (explicit lookback contract; documented that the
  Veles documentation defines no universal warmup/history rule).

### 3. `backend/app/trading/live_execution.py`

- `build_live_service` docstring and the `_make_market_context` provider
  comment updated: the live MarketContext is built from the bot's configured
  `timeframe` **and** the explicitly configured `lookback_bars`; missing
  timeframe -> `TimeframeNotConfigured`, missing explicit lookback ->
  `LookbackNotConfigured`, missing/invalid snapshot ->
  `MarketDataUnavailable`. No implicit defaults, no lookback inferred from
  indicator semantics.

### 4. `backend/app/trading/__init__.py`

- Exports `LookbackNotConfigured`.

### 5. `backend/tests/test_mvp610_market_snapshot.py`

- Removed the revision-1 `required_bars` tests (they encoded the rejected
  semantics).
- Added `test_snapshot_request_uses_explicit_lookback_from_config`: the
  snapshot request carries exactly the strategy's configured `lookback_bars`
  (7), never a derived value.
- Added `test_lookback_is_not_inferred_from_indicator_period_or_shift`: a
  config with indicator `period=9`/`shift=3` but **no** explicit lookback
  fails with `LookbackNotConfigured` (nothing is computed from the filter
  contract).
- Added `test_non_positive_lookback_rejected_by_strategy_config`
  (`lookback_bars=0` -> validation error).
- Added `test_missing_lookback_fails_snapshot_context_explicitly` (boundary:
  `LookbackNotConfigured`, zero broker requests) and
  `test_missing_lookback_fails_live_cycle_explicitly` (runtime: the cycle
  fails, zero orders).
- Updated `test_timeframe_propagates_from_strategy_config` and
  `test_snapshot_bars_drive_entry_filter_evaluation` to use an explicit
  `lookback_bars`.

### 6. `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`

- Section 28 "Per-bot timeframe" rewritten: `lookback_bars` is an explicit
  project-level parameter, not a Veles semantic; no formula, no `+1`, no
  period-as-history; missing -> `LookbackNotConfigured`, non-positive ->
  validation failure. Documented limitation: an indicator whose internal
  warmup needs more bars than the configured lookback evaluates as undefined
  -> condition False -> no signal (existing insufficient-data semantics,
  unchanged); the per-indicator warmup specification is a boundary pending
  the Veles specification.
- Section 28 "Live runtime integration" diagram/notes and "Testing" updated.

## What did NOT change (accepted parts, untouched)

- broker-neutral `MarketSnapshot` boundary;
- `MarketDataService.get_snapshot` (real broker data, `Decimal` prices,
  UTC-aware timestamps, `MarketDataUnavailable` on missing/invalid data;
  explicit positive `lookback_bars` parameter — no default inside the
  service);
- explicit per-bot timeframe (`StrategyConfig.timeframe`,
  `TimeframeNotConfigured`, `StrategyLoadError` on invalid);
- `BotRuntime.market_context_provider` and `execute_strategy()`;
- `TradingEngine` live gates (missing timeframe -> explicit cycle failure;
  snapshot without the bot-timeframe series -> no live intents);
- MVP-6.9 PositionManager quantity gate (unchanged);
- DCA/Grid mathematics and Veles Filter/Signal semantics (untouched);
- Backtest (BacktestBroker/BacktestConfig/semantics untouched);
- T-Invest read-only boundary; broker-neutral architecture (mapping stays in
  `TInvestAdapter`).

## Validation results

- `pytest`: **373 passed, 1 skipped** (revision 1 baseline: 371 passed,
  1 skipped; net +2: 4 new lookback tests added, 3 `required_bars` tests
  removed, 2 existing tests updated; the single skip is the opt-in live
  sandbox integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `npm run build`: **✓ built** (152.28 kB js / 7.72 kB css).
- Actual diff inspected (6 files): `backend/app/strategies/config.py`,
  `backend/app/trading/market_context.py`,
  `backend/app/trading/live_execution.py`,
  `backend/app/trading/__init__.py`,
  `backend/tests/test_mvp610_market_snapshot.py`,
  `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`. `git grep
  required_bars` returns no hits in `backend/`. No undocumented Veles
  semantics introduced; no Veles Filter/Signal, DCA/Grid, Backtest,
  PositionManager, broker-neutral, Decimal, UTC or T-Invest read-only
  semantics changed.

## Compliance with the review's required correction

1. Self-defined `required_bars` formula (`period + shift + 1`) — **removed
   entirely** (no formula remains).
2. `+1` for crossing operators — **removed** (not part of any lookback
   calculation anymore).
3. "Minimum history required by a Veles strategy" claim — **removed**; the
   lookback is now a separately explicitly configured project-level
   parameter, as the review permits ("оставь lookback отдельным явно
   конфигурируемым параметром").
4. Indicator period is **not** interpreted as an established history size;
   an argument's period/shift plays no role in the snapshot request.
5. The missing Veles warmup/lookback specification is **documented** as a
   limitation (TASK-09 §28 and this report); no engineering assumption
   substitutes for it.
6. The live path obtains exactly the history length the strategy contract
   explicitly configures (`lookback_bars`); nothing else is fetched.

## Known limitations

- The amount of history an indicator internally "warms up" over is not
  defined by the Veles documentation; if the configured `lookback_bars` is
  smaller than that internal need, the indicator evaluates as undefined ->
  condition False -> no signal (existing strategy-engine semantics,
  unchanged). Widening the fetch is done by explicitly raising the strategy's
  `lookback_bars`, not by inference.
- A live strategy cycle requires **both** an explicit per-bot `timeframe`
  and an explicit `lookback_bars`; a strategy version lacking either fails
  the cycle explicitly (`TimeframeNotConfigured` / `LookbackNotConfigured`)
  instead of using a default.
- The live strategy cycle trigger (scheduling) is not part of this MVP.
- No actual live order submission (T-Invest read-only), per the MVP scope.

## Documentation / specification gaps

- The Veles documentation does not define per-indicator warmup/history
  requirements nor a universal lookback rule. Per the AGENTS.md Veles
  compatibility rule, this project stops at that boundary: no rule is
  invented and no conventional value is chosen silently. If an exact
  per-indicator warmup/lookback contract is required, the Veles
  specification must be established (or clarified) first.

## Git state

- `agent/review/mvp-6.10` -> `c7429fd` (published).
- `master` unchanged; no merge/rebase; working tree clean.
- `agent/control` updated with this report only.
