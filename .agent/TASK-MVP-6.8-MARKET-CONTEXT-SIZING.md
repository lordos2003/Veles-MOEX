# MVP-6.8 — Live Market Context & Position Sizing Boundary

## Base

Start from accepted master commit:

57b192dfe5e20b744eb7441c3c2769d6e38d6db0

Do not modify master directly. Implement on local master, create one focused implementation commit, publish the result to `agent/review/mvp-6.8`.

Create a separate report on `agent/control`. Do not create CHATGPT REVIEW.

## Goal

Complete the missing production boundary between live market data, StrategyEngine evaluation and safe order sizing.

Target:

Market Data -> MarketContext -> StrategyEngine -> DCA/Grid -> Plan -> safe ExecutionIntent -> RiskManager -> OrderManager -> BrokerAdapter

Use real domain data where it already exists. Do not fabricate market data, quantity, nominal, price or position values.

## Current boundaries

MVP-6.7 intentionally left:
- no production MarketContext source;
- EntrySignal has no safe quantity;
- ExitPlan currently originates from ExitEngine with placeholder position_qty=1.0 and must not become a live exit order;
- StrategyEngine does not currently produce live entry quantity from a production sizing source;
- DCAGridEngine has base_nominal=100 as a function default, which must not be used as an implicit live financial value.

## Requirements

### 1. Production MarketContext

Find existing broker-neutral market-data services/DTOs and create the smallest production integration needed to construct MarketContext for a running Bot.

- use existing broker-neutral market-data interfaces;
- no T-Invest types in StrategyEngine or TradingEngine;
- no hardcoded prices;
- no synthetic candles;
- no fake timestamps.

If the application cannot provide required data at this boundary, keep the boundary explicit and report the missing dependency. Do not fabricate data.

### 2. Position sizing

Define the existing domain source for the first live order quantity.

The source must be explicit.

Acceptable sources are existing Bot/trading configuration or an already implemented domain object representing order nominal/quantity.

Do not invent a new financial default.

Do not use 100 as a live nominal, 1.0 as a live quantity, or arbitrary quantities only to make tests pass.

If no authoritative sizing source exists, implement only the typed boundary and block live execution until configured.

### 3. Bot-specific configuration

A running Bot must use its own configuration.

Do not copy StrategyConfig.risk into the global RiskManager.

Keep StrategyVersion configuration immutable.

### 4. Strategy -> DCA/Grid

Use the existing DCAGridEngine.

Do not reimplement grid mathematics.

The live strategy path must pass an explicit base nominal/quantity source into the existing engine.

The existing Decimal("100") default must never be relied upon by live execution.

### 5. Entry intent

Create a live entry intent only when all fields are real and valid:
- bot_id;
- instrument;
- side;
- positive quantity;
- MARKET or valid LIMIT price;
- deterministic idempotency identity.

Route through:

BotRuntime -> TradingEngine -> RiskManager -> OrderManager

No direct StrategyEngine -> OrderManager path.

### 6. Exit boundary

Do not enable live ExitPlan conversion in this task.

The existing ExitEngine placeholder position_qty=1.0 is not an acceptable live quantity.

Keep the explicit non-conversion boundary until a later task wires PositionManager quantity.

### 7. Lifecycle

Preserve MVP-6.5 semantics:
- strategy/context/sizing failure during START -> ERROR;
- RiskManager slot is not leaked;
- START rejection remains explicit API error;
- STOP and EMERGENCY_STOP semantics remain unchanged;
- persisted restart semantics remain unchanged.

Do not redesign BotRuntime.

### 8. Broker neutrality

No imports from app.brokers.tinvest*, T-Invest protocol types or T-Invest transport code inside StrategyEngine, DCA/Grid, sizing domain or TradingEngine.

Broker-specific market-data acquisition belongs below the broker-neutral boundary.

## Tests

Add about 10 focused new tests. Do not duplicate existing MVP-6.5/6.6/6.7 regression tests.

Cover:
1. real MarketContext reaches StrategyEngine;
2. missing market data blocks live strategy execution;
3. no fabricated MarketContext;
4. Bot-specific sizing source is used;
5. missing sizing blocks execution;
6. DCAGridEngine receives explicit live sizing;
7. DCAGrid default 100 is never used by live path;
8. valid generated entry intent contains positive real quantity;
9. invalid quantity is rejected before OrderManager;
10. full path remains RiskManager-gated;
11. live ExitPlan with placeholder quantity remains blocked;
12. strategy/context/sizing failure does not consume RiskManager slot.

Run the full existing backend suite as regression.

## Explicit non-goals

Do not implement:
- new indicators;
- Veles filter/signal redesign;
- DCA/Grid mathematical changes;
- Exit Engine redesign;
- live exit execution;
- Backtest changes;
- T-Invest execution changes;
- MCP;
- OrderStateStream;
- recovery algorithm changes;
- UI;
- authentication;
- optimizer;
- financial tuning;
- unrelated refactoring.

## Git/report

One focused implementation commit.

Do not push or merge master.

Publish implementation to `agent/review/mvp-6.8`.

Create/update `.agent/REPORT-MVP-6.8.md` on `agent/control`.

Report:
- implementation commit;
- exact MarketContext source;
- exact sizing source;
- how live path uses explicit sizing;
- how missing data/config is blocked;
- why exit placeholder remains blocked;
- tests and commands;
- git state.

If a required production source does not exist, stop at the architectural boundary and report the missing dependency instead of inventing one.