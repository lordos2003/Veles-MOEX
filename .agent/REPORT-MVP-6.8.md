# Veles-MOEX — REPORT: MVP-6.8 Market Context & Position Sizing Boundary

## Implementation commit

`b2c4ee27cdd1bcf67bb69c2f22374cb062bebb52` — "feat: implement MVP-6.8 market
context and position sizing boundary" (single focused commit on local `master`).

Published to `agent/review/mvp-6.8` (HEAD = `b2c4ee2`). `master` NOT pushed; no
merge/rebase.

## Exact MarketContext source

`backend/app/trading/market_context.py` — `build_market_context(market_data,
instrument_figi)` is the smallest broker-neutral production integration:

- fetches the real last trade price via the existing broker-neutral
  `MarketDataService.get_last_price()` (depends only on the `BrokerAdapter`);
- builds a `MarketContext(price, timestamp)` from real data — no hardcoded
  price, no synthetic candle, no fake timestamp;
- raises `MarketContextUnavailable` when the live price is missing or
  non-positive (no fabricated substitute).

`LiveExecutionService` gained a `build_context(instrument_figi)` wrapper and
`build_live_service()` wires a real `MarketDataService(broker)` into the live
service.

**Documented missing dependency:** the candle/snapshot source (required by the
Entry Engine filter evaluation) and the per-bot `timeframe` are not wired. The
boundary supplies a real last price and timestamp; strategy evaluation that
needs a live `Snapshot` remains blocked until a candle/timeframe source is
configured. No values are invented.

## Exact sizing source

`backend/app/trading/sizing.py` — `PositionSizing(base_nominal)` (frozen) and
`SizingNotConfigured`. `PositionSizing.resolve_base_nominal()` returns the
positive base nominal or raises `SizingNotConfigured`.

There is **no authoritative position-sizing source** in the Bot/trading
configuration, so:

- the production per-bot `TradingEngine` is created with `sizing=None`
  (`build_live_service._make_bot_engine`); and
- `TradingEngine.process()` raises `SizingNotConfigured` when no sizing source
  is configured.

No new financial default was invented: the `Decimal("100")` engine default and
`1.0`/`100` placeholders are never used as live values.

## How the live path uses explicit sizing

`StrategyEngine.evaluate(config, context, *, base_nominal=None)` now builds the
DCA/Grid plan items through the existing `DCAGridEngine` only when an explicit
live sizing source (`base_nominal`) is supplied and the entry signal fires;
`Plan.grid` is populated from the grid state's eligible orders. The live path:

`BotRuntime.execute_strategy(MarketContext)` -> `TradingEngine.process()` ->
`StrategyEngine.evaluate(..., base_nominal=...)` -> DCA/Grid `Plan.grid` ->
`plan_to_intents()` -> `RiskManager.check_order()` -> `OrderManager.submit()`.

When `base_nominal` is `None` the engine keeps its previous behaviour (no grid
items), so Backtest and the existing strategy tests are unchanged.

## How missing data/config is blocked

- Missing market data -> `MarketContextUnavailable` (no fabricated price).
- Missing sizing source -> `SizingNotConfigured` in `TradingEngine.process()`
  (no fabricated order quantity).
- Both block live order generation; nothing reaches the broker.
- A sizing/strategy failure during START (via the per-bot engine factory) moves
  the bot to ERROR and does not consume the Risk Manager concurrent-bot slot
  (verified by test).

## Why the exit placeholder remains blocked

`ExitPlan` quantities still originate from the `position_qty=1.0` placeholder in
`StrategyEngine.evaluate()`. `plan_to_intents()` does NOT convert exit plans, so
a live exit remains blocked until the Position Manager supplies a real quantity.
The conversion boundary is unchanged; no fabricated exit quantity.

## Tests

`backend/tests/test_mvp68_market_context_sizing.py` (13 focused tests; the task
asked for ~10):

1. real MarketContext built from broker data;
2. MarketContext reaches the StrategyEngine and drives the DCA/Grid plan;
3. missing market data blocks live strategy execution;
4. no fabricated MarketContext outside the boundary module;
5. bot-specific sizing source is used;
6. missing sizing blocks execution;
7. DCAGridEngine receives explicit live sizing;
8. DCAGrid default 100 is never used by the live path;
9. valid generated entry intent contains a positive real quantity;
10. invalid quantity is rejected before the Order Manager;
11. full path remains Risk-Manager-gated;
12. live ExitPlan with placeholder quantity remains blocked;
13. sizing failure during START does not consume the Risk Manager slot.

Existing suites were updated only where the new sizing boundary is now a
required input for `TradingEngine.process()`:
- `tests/test_trading_risk.py::test_trading_engine_process_routes_through_risk`
  supplies a `PositionSizing` and a `**kwargs`-compatible stub engine;
- `tests/test_strategy_live_integration.py` supplies a `PositionSizing` in its
  per-bot engine factory and makes the stub engine accept the `base_nominal`
  keyword. Asserts were unchanged.

## Commands / results

- `pytest` (backend): **336 passed, 1 skipped** (was 323 passed, 1 skipped;
  +13 new tests; the single skip is the opt-in live sandbox integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `npm run build` (frontend): **✓ built in 6.75s**.

## Git state

- Implementation commit: `b2c4ee27cdd1bcf67bb69c2f22374cb062bebb52`.
- `agent/review/mvp-6.8` -> `b2c4ee2` (published).
- `master` NOT pushed; working tree clean; no merge/rebase.
- `agent/control` updated with this report only.

## Known limitations / boundaries

- No authoritative position-sizing source: `process()` blocks live strategy
  execution until one is configured. Typed boundary + explicit error; no
  invented financial default.
- No candle/snapshot source or per-bot timeframe: live entry-filter evaluation
  that needs a `Snapshot` remains blocked.

## Acceptance / publication

MVP-6.8 **ACCEPTED by ChatGPT** and published to `origin/master`:
`origin/master` is at `b2c4ee27cdd1bcf67bb69c2f22374cb062bebb52`
(fast-forward `57b192d..b2c4ee2`). No further push/merge is required.

