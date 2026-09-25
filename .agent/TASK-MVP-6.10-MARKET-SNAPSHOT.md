# TASK-MVP-6.10 — Live Market Snapshot & Per-Bot Timeframe

## Status

**READY FOR IMPLEMENTATION**

Control branch: `agent/control`  
Implementation branch: `agent/review/mvp-6.10`  
Base: `master @ cdc10296e32509f2d716c85c1b58e62a9b01b2cf`

## Objective

Provide the live Strategy path with a real broker-neutral market snapshot using the timeframe configured by the individual bot/strategy.

The implementation must close the current MVP-6 boundary:

- candle/snapshot source;
- per-bot timeframe propagation.

Production position sizing remains governed by the already accepted MVP-6.9 PositionManager boundary.

## Scope

### 1. MarketSnapshot

Introduce or complete a broker-neutral snapshot/context contract containing the minimum data required by the current live Strategy path.

At minimum, preserve:

- instrument identity / FIGI;
- timeframe;
- timestamp;
- last price;
- candle information when required by the existing Strategy contract.

Use existing domain types where possible. Do not create parallel representations without a concrete architectural reason.

### 2. MarketDataService

Provide the broker-neutral service used by live runtime to obtain the snapshot.

Requirements:

- Strategy must not depend on T-Invest types;
- T-Invest-specific mapping remains inside `TInvestAdapter` / market-data integration;
- use real broker data;
- preserve `Decimal` prices;
- timestamps remain timezone-aware UTC.

### 3. Per-bot timeframe

The timeframe must originate from the bot's own strategy/configuration.

Required path:

`Bot/StrategyVersion -> timeframe -> MarketDataService -> MarketSnapshot -> Strategy`

Do not introduce a global runtime timeframe or an implicit production default.

If the timeframe is missing or invalid, fail/block the processing cycle explicitly.

### 4. Live runtime integration

Integrate the snapshot into the existing:

`BotRuntime -> Strategy -> DCA/Grid -> TradingEngine`

path.

The existing MVP-6.9 quantity invariant remains mandatory:

- PositionManager remains the authoritative live quantity source;
- unresolved position state blocks live ExecutionIntent creation/submission.

A missing or invalid market snapshot must likewise prevent a live strategy cycle from producing an executable intent.

### 5. Backtest isolation

Do not alter existing BacktestBroker/DCA/Grid mathematics or Backtest semantics.

The live market-data implementation must remain separable from backtest data.

### 6. Tests

Add focused regression tests covering:

1. valid MarketSnapshot;
2. timeframe propagation from bot/strategy configuration;
3. correct snapshot retrieval request;
4. missing timeframe;
5. invalid timeframe;
6. missing/invalid market snapshot;
7. preservation of the MVP-6.9 position-state blocking invariant;
8. existing full test suite.

## Explicit architectural constraints

- Keep broker integration behind `BrokerAdapter`.
- Keep broker DTOs separate from domain models.
- Use `Decimal` for prices/monetary values.
- Normalize timestamps to UTC.
- Do not invent market data.
- Do not invent timeframe or quantity defaults.
- Preserve Veles Filter/Signal semantics.
- Preserve DCA/Grid mathematics.
- Keep live execution isolated from backtest logic.
- Implement only the dependencies required by this MVP.

## Out of scope

- T-Invest order submission;
- live trading activation;
- Multi-Take;
- Signal TP;
- Stop Loss;
- Trailing;
- recovery;
- optimizer;
- UI redesign;
- Paper Trading;
- direct MOEX API.

## Acceptance criteria

The MVP is ready for ChatGPT review only when:

- implementation is on `agent/review/mvp-6.10`;
- `agent/control` contains an implementation REPORT;
- actual diff is limited to MVP-6.10 scope;
- tests cover the new boundaries;
- full test suite passes;
- lint/type/build checks used by the repository pass;
- no fabricated/default market data, timeframe, or quantity exists in the live path;
- MVP-6.9 position-state invariant remains intact.

OpenCode must not publish to `master`. ChatGPT performs the independent review first.
