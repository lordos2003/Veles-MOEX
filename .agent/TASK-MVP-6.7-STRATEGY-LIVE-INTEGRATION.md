# MVP-6.7 — Strategy → Bot Runtime → Trading Engine

## Status

Implementation task.

Base commit:

`b2b199e2d73f7d1ec32abd4f7128e6f7a5a04f1b`

Do not push or merge `master).

## 1. Goal

Connect the already implemented Strategy Engine to the live Bot Runtime and Trading Engine without duplicating strategy, DCA/Grid or Exit logic.

Target path:

```
Bot
 |
 | StrategyVersion
 v
StrategyConfig
 |
 v
StrategyEngine
 |
 v
BotRuntime
 |
 v
TradingEngine
 |
 v
RiskManager
 |
 v
OrderManager
 |
 v
BrokerAdapter
```

The implementation must use the existing Strategy Engine and existing broker-neutral execution components.

## 2. Current boundary

Current production live execution supports:

`LiveExecutionService.submit() -> BotRuntime -> TradingEngine.submit_intent() -> RiskManager -> OrderManager -> BrokerAdapter`

The Strategy -> TradingEngine path is not production-wired.

`TradingEngine.process()` already exists as an integration seam, but it must not be called with missing StrategyEngine/StrategyConfig.

## 3. Required work

### 3.1 Bot → StrategyVersion

A Bot already contains `strategy_version_id`.

Implement the minimum repository/service boundary needed to load the Bot's referenced StrategyVersion and its immutable configuration.

Requirements:

- use the existing `Bot`, `Strategy`, and `StrategyVersion` models;
- do not create a second strategy storage model;
- do not mutate StrategyVersion;
- validate/load the stored configuration through the existing `StrategyConfig` model;
- invalid or missing strategy configuration must block execution explicitly;
- do not invent financial defaults.

### 3.2 StrategyEngine composition

Create the production composition needed to construct the existing:

- `EntryEngine`;
- `DCAGridEngine`;
- `ExitEngine`;
- `StrategyEngine`.

Do not rewrite their calculations.

The composition must remain broker-neutral.

No T-Invest imports in Strategy Engine code.

### 3.3 Per-bot runtime

Each Bot Runtime must have access to its own immutable StrategyConfig/StrategyVersion.

Do not put one global strategy configuration into all bots.

The runtime must not become RUNNING unless the required strategy configuration can be loaded and validated.

If strategy loading fails:

- lifecycle state must become ERROR;
- the API must report an explicit lifecycle/start failure;
- RiskManager must not leave a concurrent-bot slot occupied.

Preserve the existing MVP-6.5 restart semantics.

### 3.4 MarketContext boundary

Define the minimum broker-neutral input boundary required to evaluate the Strategy Engine for a live Bot.

The boundary must provide enough information for the existing `StrategyEngine.evaluate()` / Entry Engine path.

Do not implement a new market-data subsystem in this task.

If the existing application has no safe production source for a complete `MarketContext`, keep that source explicitly injectable and document the production boundary instead of fabricating market data.

No hardcoded prices.

No fake candles.

No fake positions.

### 3.5 Strategy → TradingEngine

Wire the existing Strategy Engine into the Trading Engine without bypassing RiskManager.

The intended flow is:

```
MarketContext
    |
StrategyEngine.evaluate()
    |
Plan
    |
TradingEngine
    |
RiskManager.check_order()
    |
OrderManager.submit()
```

The implementation must not call `OrderManager.submit()` directly from Strategy Engine code.

The Risk Manager remains authoritative.

### 3.6 ExecutionIntent

Use the existing `ExecutionIntent` domain object.

If conversion from `EntrySignal` / `Plan` to `ExecutionIntent` is required, implement that conversion at the Trading Engine / runtime orchestration boundary.

Do not put broker-specific fields into Strategy domain objects.

Do not invent order quantities or prices when the current domain does not provide them safely.

If the existing Strategy/DCA/Exit output is insufficient for a real live intent, make the missing boundary explicit and stop at that boundary rather than fabricating a value.

### 3.7 DCA/Grid and Exit

Do not reimplement DCA/Grid or Exit logic.

For this task, only establish the correct integration boundary.

The existing Strategy Engine currently produces a `Plan`; preserve that model unless a minimal extension is required for the integration.

Do not silently turn the existing `position_qty=1.0` Exit placeholder into a live order quantity.

A live quantity must come from real domain/runtime state.

If that source is not available, document the boundary and do not submit such an exit.

## 4. Bot lifecycle requirements

Preserve all accepted MVP-6.5 behavior:

- STOPPED -> STARTING -> RUNNING;
- ERROR -> STARTING;
- normal STOP:
  `RUNNING -> STOP_REQUESTED -> cancel orders -> RiskManager.stop_bot() -> STOPPED`;
- cancellation failure -> ERROR before RiskManager slot release;
- EMERGENCY_STOP blocks new intents and cancels active bot orders;
- restart never automatically reactivates a bot;
- persisted RUNNING/STARTING restores to ERROR;
- explicit START is required after restart;
- rejected START persists ERROR;
- no disconnected fallback BotRuntimeManager.

A Bot must not generate strategy execution while it is not RUNNING.

## 5. Strategy configuration and risk

Strategy risk configuration and execution risk are separate concepts.

Do not bypass the authoritative production RiskManager.

Do not silently copy StrategyConfig.risk into global RiskManager limits.

If per-bot risk configuration is not yet supported by the existing RiskManager boundary, document this as a limitation. Do not invent precedence rules.

## 6. What is explicitly out of scope

Do not implement:

- new indicators;
- new Veles strategy semantics;
- changes to Filter/Signal semantics;
- new DCA/Grid mathematics;
- new Exit mathematics;
- Backtest changes;
- T-Invest changes;
- T-Invest MCP;
- OrderStateStream changes;
- recovery algorithm changes;
- UI redesign;
- authentication/authorization;
- optimizer;
- financial parameter tuning;
- unrelated refactoring;
- generic rule/expression-tree abstraction.

## 7. Acceptance criteria

### Architecture

- Strategy Engine remains broker-neutral.
- Bot Runtime uses the Bot's own StrategyVersion.
- StrategyVersion is immutable.
- No T-Invest dependency enters Strategy Engine or Trading Engine.
- RiskManager remains mandatory before order submission.
- No direct StrategyEngine -> OrderManager path.

### Lifecycle

- Existing MVP-6.5 tests remain green.
- A Bot with valid StrategyVersion can load its StrategyConfig.
- A Bot with missing/invalid StrategyVersion cannot enter RUNNING.
- Failed strategy loading does not consume a RiskManager concurrent-bot slot.
- Restart semantics remain unchanged.

### Market data

- The MarketContext source is explicit.
- No fabricated market data is used.
- If live MarketContext is not production-available, the code must expose an injectable boundary and document it.

### Execution

- Strategy evaluation can reach the Trading Engine through the intended broker-neutral path.
- RiskManager is called before OrderManager.
- No live order is created from fabricated quantity/price.
- Existing `ExecutionIntent` idempotency semantics remain intact.

### Tests

At minimum cover:

1. valid Bot -> StrategyVersion -> StrategyConfig;
2. missing StrategyVersion;
3. invalid StrategyVersion config;
4. failed strategy load -> ERROR;
5. failed strategy load does not consume concurrent-bot slot;
6. valid strategy cannot execute while Bot is not RUNNING;
7. Strategy plan reaches TradingEngine;
8. RiskManager rejects before OrderManager;
9. no direct StrategyEngine -> OrderManager call;
10. no fabricated MarketContext;
11. restart semantics remain green;
12. existing MVP-6.5 and MVP-6.6 tests remain green.

## 8. Git / reporting rules

- Work from `b2b199e2d73f7d1ec32abd4f7128e6f7a5a04f1b`.
- One focused implementation commit.
- Do not push `master`.
- Publish/update `agent/review/mvp-6.7`.
- Create/update a separate `.agent/REPORT-MVP-6.7.md` on `agent/control`.
- REPORT must contain:
  - implementation commit;
  - exact files changed;
  - exact StrategyVersion loading path;
  - StrategyEngine composition;
  - MarketContext source/boundary;
  - lifecycle behavior;
  - ExecutionIntent conversion;
  - tests;
  - lint/build results;
  - Git state.
- Do not write `CHATGPT REVIEW`.
- Do not merge or rebase.
- Do not make unrelated fixes.

The implementation report is evidence only. Independent review must inspect the actual commit and diff.
