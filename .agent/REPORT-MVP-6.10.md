# Veles-MOEX — REPORT: MVP-6.10 Live Market Snapshot & Per-Bot Timeframe

## Implementation commit

`4c4e8fa` — "feat: implement MVP-6.10 live market snapshot and per-bot
timeframe" (single focused commit on `agent/review/mvp-6.10`).

- Base: `master @ cdc1029` (current accepted master, includes accepted
  MVP-6.9).
- Review branch HEAD: `4c4e8fa` (published to `origin/agent/review/mvp-6.10`).
- `master` NOT modified; no merge/rebase.

## Objective

Close the MVP-6.8 boundary: the live Strategy path now receives a real
broker-neutral market snapshot (last price + candle history) built with the
timeframe configured by the bot's own strategy. The candle/snapshot source and
the per-bot timeframe are no longer "not wired". Production position sizing
remains governed by the accepted MVP-6.9 PositionManager boundary.

## What was implemented

### 1. MarketSnapshot contract (existing domain types reused)
`backend/app/domain/marketdata.py`

- Added the broker-neutral frozen dataclass `MarketSnapshot`
  (`figi`, `timeframe`, timezone-aware UTC `timestamp`, `Decimal
  last_price`, `tuple[Candle, ...]` candle history). It reuses the existing
  `Candle`/`LastPrice`/`Timeframe` domain types — no parallel representation.
- Added the broker-neutral domain error `MarketDataUnavailable`.

### 2. MarketDataService snapshot
`backend/app/services/market_data.py`

- Added `MarketDataService.get_snapshot(figi, timeframe, lookback_bars) ->
  MarketSnapshot`:
  - validates the timeframe against the supported set and the positive
    lookback;
  - assembles the snapshot exclusively from real broker data: the last trade
    price (`get_last_price`) plus the most recent `lookback_bars` candles
    (`get_candles`) for the instrument/timeframe, with one extra bar of width
    so the currently forming candle is included;
  - raises `MarketDataUnavailable` on a missing/non-positive last price or an
    empty candle history (no synthetic value is substituted) and
    `InstrumentNotFoundError` for an unknown instrument.
- The Strategy path never sees T-Invest types; T-Invest-specific mapping
  stays inside `TInvestAdapter` (unchanged). Prices stay `Decimal`, timestamps
  timezone-aware UTC.

### 3. Per-bot timeframe (no global/implicit default)
`backend/app/strategies/config.py`

- Added `StrategyConfig.timeframe: Timeframe | None = None` — the bot's own
  market-data timeframe, part of the immutable StrategyVersion configuration
  (`Bot/StrategyVersion -> timeframe`). A missing timeframe is `None` and
  fails the live cycle explicitly; an invalid value fails configuration
  validation at load time (`StrategyLoadError`).
- Added `required_bars(StrategyConfig)` — the minimum real candle history
  derived from the strategy's own entry/signal filter contracts (indicator
  warmup + shifts; MACD slow+signal; ADX ~2*period; +1 for the previous bar
  used by cross operators; always >= 2). No invented default lookback.

### 4. Live market-context boundary
`backend/app/trading/market_context.py`

- Added `TimeframeNotConfigured` (explicit cycle failure, no implicit
  default).
- Added `market_snapshot_to_context(MarketSnapshot) -> MarketContext` (candles
  -> the bot-timeframe bar series; last price and snapshot timestamp
  preserved; an empty snapshot yields an empty series, never fabricated bars).
- Added `build_market_snapshot_context(market_data, instrument_figi,
  strategy_config) -> MarketContext`: the timeframe and the lookback
  (`required_bars`) originate from the bot's own strategy configuration;
  `market_data` is duck-typed on `get_snapshot(...)` so the boundary stays
  broker-neutral. Missing timeframe -> `TimeframeNotConfigured`; missing
  invalid data -> `MarketDataUnavailable` (propagated from the service).
- The existing MVP-6.8 `build_market_context` (last price only) is preserved
  unchanged.

### 5. TradingEngine live gates
`backend/app/trading/engine.py`

- `process()` for a live per-bot engine (`instrument_figi` set) now
  enforces:
  - `_require_live_timeframe()`: a missing per-bot timeframe raises
    `TimeframeNotConfigured` **before** any evaluation (the processing cycle
    fails explicitly; no implicit default timeframe);
  - `_snapshot_gates_execution(context, timeframe)`: a market context without
    a non-empty bar series for the bot's timeframe blocks **all** live
    ExecutionIntent creation/submission for the cycle (missing snapshot,
    empty series, or a series for a different timeframe => no live order at
    all), with the same blocking semantics as the MVP-6.9 position-state gate.
- Generic/Backtest engines (no `instrument_figi`) are not gated. The
  MVP-6.9 position-state invariant (`_position_gates_execution`) is
  unchanged and remains mandatory.

### 6. BotRuntime market-context provider
`backend/app/trading/bot_lifecycle.py`

- `BotRuntime` gained `market_context_provider: (BotStrategy) ->
  Awaitable[MarketContext]`.
- `execute_strategy(context=None)`: when called without an explicit context,
  the provider builds the live snapshot for the bot's own configured
  timeframe from real market data. A missing provider/strategy or a
  missing/invalid snapshot fails the cycle explicitly (no fabricated market
  data). Explicit-context callers are unaffected.

### 7. Production wiring
`backend/app/trading/live_execution.py`

- `build_live_service` wires the bot runtime's `market_context_provider`:
  per-bot `build_market_snapshot_context(market_data, instrument.figi,
  bot_strategy.config)` using the already-wired broker-neutral
  `MarketDataService` — so the live cycle path is
  `Bot/StrategyVersion -> timeframe -> MarketDataService.get_snapshot ->
  MarketSnapshot -> MarketContext -> BotRuntime.execute_strategy ->
  StrategyEngine -> DCA/Grid/Exit -> TradingEngine -> RiskManager ->
  OrderManager`.
- Docstrings updated (MVP-6.10 boundary; the MVP-6.8 "candle/snapshot source
  not wired" boundary is closed).

### 8. Exports / documentation

- `app/trading/__init__.py`: exports `TimeframeNotConfigured`,
  `build_market_snapshot_context`, `market_snapshot_to_context`.
- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`: new section 28
  (Market snapshot & per-bot timeframe — MVP-6.10).

## Architecture decisions / boundaries

- The authoritative path is
  `T-Invest -> TInvestAdapter (mapping) -> BrokerAdapter -> MarketDataService
  -> MarketSnapshot -> MarketContext -> StrategyEngine -> Plan ->
  ExecutionIntent -> RiskManager -> OrderManager`. Broker integration stays
  behind `BrokerAdapter`; broker DTOs never leak into domain/strategy layers.
- No global runtime timeframe, no implicit production default, no fabricated
  market data: missing/invalid timeframe or snapshot fails/blocks the live
  processing cycle explicitly.
- Lookback is derived from the strategy's own filter contract
  (`required_bars`), not a constant default.
- Backtest isolation preserved: `BacktestConfig.timeframe`, BacktestBroker,
  DCA/Grid mathematics and Veles Filter/Signal semantics are untouched; the
  live market-data path is separable from backtest data.
- T-Invest stays read-only; no actual live order submission is added.

## Explicit confirmation: no fabricated/default values in the live path

- No default timeframe: `StrategyConfig.timeframe` defaults to `None` and a
  live cycle without it raises `TimeframeNotConfigured`; no runtime
  timeframe constant exists in `app/trading` or `app/services`.
- No default lookback: `get_snapshot` requires an explicit positive
  `lookback_bars`; the only caller derives it from the strategy contract.
- No default quantity: unchanged (MVP-6.9 PositionManager remains the only
  authoritative live quantity source).
- No fabricated market data: `get_snapshot` and the context boundary raise
  instead of substituting values.

## Tests

`backend/tests/test_mvp610_market_snapshot.py` (21 focused tests):

1. valid MarketSnapshot from broker data (FIGI/timeframe/UTC timestamp/
   Decimal prices/candle history);
2. MarketSnapshot -> MarketContext value preservation;
3. timeframe propagation from the strategy configuration;
4. timeframe propagation through the bot runtime (provider receives the bot's
   own strategy with its own timeframe);
5. correct snapshot retrieval request (FIGI, timeframe, window =
   (lookback+1) bars of width);
6. snapshot request uses `required_bars` from the strategy contract;
7. missing timeframe fails the snapshot context explicitly (no broker
   request issued);
8. missing timeframe fails the live processing cycle explicitly
   (`TimeframeNotConfigured`, no orders);
9. invalid timeframe rejected by `StrategyConfig` validation;
10. invalid timeframe blocks strategy version load (`StrategyLoadError`);
11. missing timeframe loads but blocks the live cycle (no implicit default);
12. unknown instrument -> `InstrumentNotFoundError`;
13. non-positive last price -> `MarketDataUnavailable`;
14. empty candle history -> `MarketDataUnavailable`;
15. missing snapshot blocks the runtime strategy cycle (no orders);
16. snapshot without the bot-timeframe series blocks live intents;
17. empty snapshot series blocks live intents;
18. missing snapshot blocks live intents;
19. MVP-6.9 invariant: valid snapshot + no position -> no live order at all;
20. MVP-6.9 invariant: valid snapshot + position -> real position quantity
    reaches the exit order (grid + exit submitted);
21. snapshot bars drive the entry-filter evaluation (SMA condition fires,
    grid built from the explicit base nominal).

Existing tests updated only where the live contract intentionally changed:
`tests/test_mvp69_position_state.py` live per-bot strategies now carry
`timeframe=Timeframe.MIN_5` (the live per-bot engine now requires the bot's
own timeframe).

## Commands / results

- `pytest`: **369 passed, 1 skipped** (was 348 passed, 1 skipped; +21 new
  tests; the single skip is the opt-in live sandbox integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `npm run build`: **✓ built** (152.28 kB js / 7.72 kB css).

## Git state

- Review branch `agent/review/mvp-6.10` -> `4c4e8fa` (published).
- `master` unchanged at `cdc1029`; no merge/rebase; working tree clean.
- `agent/control` updated with this report only.

## Known limitations / boundaries

- The live strategy cycle trigger (scheduling of `execute_strategy` cycles)
  is not part of this MVP; the snapshot path is wired and ready for it.
- Multi-timeframe filter arguments (a filter referencing a timeframe other
  than the bot's configured one) still need that additional series to be
  fetchable for full evaluation; the MVP-6.10 snapshot provides the bot's
  configured timeframe only, and the live gate requires exactly that series
  (documented boundary; higher-timeframe series fetching is a follow-up).
- No actual live order submission is added (T-Invest read-only), per the
  MVP scope.
