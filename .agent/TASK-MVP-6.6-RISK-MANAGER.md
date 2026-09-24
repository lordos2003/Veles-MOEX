# Veles-MOEX — MVP-6.6 Risk Manager Execution Preconditions

## Status

Task for OpenCode implementation. Start from `b2b199e2d73f7d1ec32abd4f7128e6f7a5a04f1b`.

## Goal

Complete the execution-side Risk Manager preconditions that are explicitly required by the architecture and MVP-6 live-trading specification.

MVP-6.5 already provides the bot lifecycle gate. This task must extend the Risk Manager without bypassing that gate.

## Current verified gap

The current `RiskManager.check_order()` enforces only:

- emergency stop;
- maximum position size;
- daily loss limit.

The architecture/specification also requires the execution gate to be able to verify:

- bot is running;
- instrument is allowed;
- trading session / instrument status permits trading;
- quantity is positive and valid;
- price is valid for the instrument;
- required funds / position capacity are available;
- configured execution limits.

The current production `build_live_service()` creates an empty `RiskManager` with no configured limits source.

Do not invent financial defaults.

## Scope

Implement only the broker-neutral execution-side risk preconditions that can be supported by existing domain/adapter data.

### 1. Risk checks

Extend `RiskManager` with explicit checks for:

- positive quantity;
- valid limit price when the intent is LIMIT;
- instrument/trading permission;
- configured position limit;
- configured daily loss limit;
- emergency stop.

Do not duplicate bot RUNNING state inside RiskManager. Bot lifecycle remains the upstream lifecycle gate.

Do not add autonomous risk calculations or financial tuning.

### 2. Instrument/session status

Use existing broker-neutral instrument/status data if already available.

If the current `ExecutionIntent` does not contain enough information to perform a check, make the smallest broker-neutral domain change required.

Do not import T-Invest into RiskManager.

Do not hardcode MOEX session rules.

If a required fact cannot be supplied by the current architecture, define a clear broker-neutral dependency/interface rather than fabricating the value.

### 3. Funds / capacity

Add a broker-neutral risk dependency for available funds/capacity only if existing domain data supports it.

Do not create fake account balances.

Do not introduce financial defaults.

If the required broker fact is not yet available, document the exact boundary and leave the check explicitly unavailable rather than silently passing a fabricated value.

### 4. Risk configuration

Do not hardcode production limits.

If there is no existing configuration source for RiskLimits, add only the minimal typed configuration boundary needed to supply configured limits.

Keep configuration separate from strategy parameters.

Do not introduce a new general configuration subsystem.

### 5. Integration

Preserve the existing path:

`BotRuntime -> TradingEngine -> RiskManager -> OrderManager -> BrokerAdapter`

`RiskManager.check_order()` remains authoritative before every live order.

MVP-6.5 bot lifecycle remains authoritative for START/STOP/EMERGENCY_STOP.

Do not move lifecycle state into RiskManager.

### 6. Tests

Add focused tests for:

1. zero quantity rejected;
2. negative quantity rejected;
3. invalid LIMIT price rejected;
4. MARKET intent does not require a limit price;
5. emergency stop rejects;
6. configured position limit rejects;
7. configured daily loss limit rejects;
8. allowed order passes;
9. configured instrument/status restriction rejects;
10. no fake funds/capacity data is used;
11. RiskManager remains broker-neutral;
12. existing BotRuntime lifecycle tests remain green.

Use existing project conventions.

## Explicitly out of scope

- Strategy Engine integration;
- TradingEngine.process production wiring;
- DCA/Grid;
- Exit Engine;
- Backtest;
- T-Invest-specific logic;
- MCP;
- OrderStateStream;
- recovery algorithm;
- UI;
- authentication/authorization;
- optimizer;
- autonomous financial parameter tuning;
- unrelated refactoring.

## Veles reference

Do not invent user-facing trading semantics. Veles Help Center remains the functional reference.

This task is only about the execution risk gate already defined by the Veles-MOEX architecture.

## Git

- Work from `b2b199e2d73f7d1ec32abd4f7128e6f7a5a04f1b`.
- One focused implementation commit.
- Do not push/merge `master`.
- Publish the implementation on `agent/review/mvp-6.6`.
- Update a separate `.agent/REPORT-MVP-6.6.md` on `agent/control`.
- REPORT must state:
  - exact implemented checks;
  - any broker-neutral dependency added;
  - exact configuration source, if added;
  - explicit unavailable boundaries;
  - tests and their result;
  - lint/build result;
  - implementation commit;
  - review branch;
  - no master push.
- Do not write `CHATGPT REVIEW`.
