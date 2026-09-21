# Task №7 — Veles-compatible DCA / Grid Engine MVP-4

## Goal

Implement the DCA / Grid engine for Veles-MOEX using the Veles Help Center as the functional and terminology reference.

The engine must reproduce the Veles user-facing DCA/Grid model first and adapt only where MOEX/T-Invest execution constraints require it.

## Veles reference

Primary references:

- Veles Help Center — «Режим торговли»
- Veles Help Center — «Что такое усреднение, Мартингейл и логарифм»
- Veles Help Center — «Полный список настроек бота»
- Existing project Veles engineering reference
- Architecture & Product Specification v1.0

Relevant Veles behavior:

### Trading modes

Veles has three DCA/trading modes:

1. **Простой**
   - automatically calculates a limit-order grid;
   - uses:
     - Перекрытие изменения цены
     - Сетка ордеров
     - % Мартингейла
     - Отступ первого ордера
     - Логарифмическое распределение
     - Частичное выставление сетки
     - Подтяжка сетки

2. **Свой**
   - user explicitly defines offset and nominal volume for each order;
   - supports a single order by setting volume to 100%;
   - supports arbitrary manually defined DCA levels.

3. **Сигнал**
   - first order can be market when offset = 0 or limit when offset > 0;
   - each subsequent averaging order is a market order only when:
     1. configured indicator/filter signal occurs;
     2. minimum offset from the previous order or configured reference price is satisfied.

## Scope

Implement only the DCA/Grid engine and its integration with the existing BacktestBroker / Position model.

### Required domain model

Create broker-agnostic models for:

- TradingMode: SIMPLE / CUSTOM / SIGNAL
- GridConfig
- GridOrderPlan
- GridLevel
- DCAOrder
- GridState

Do not put T-Invest-specific logic in the DCA/Grid engine.

## SIMPLE mode

Support:

### 1. Перекрытие изменения цены

This is the total percentage price range between the first and last grid order.

For LONG the grid extends downward from the first order.

For SHORT the grid extends upward from the first order.

### 2. Сетка ордеров

Number of planned orders in the grid.

The first order is part of the configured grid.

### 3. Отступ первого ордера

For LONG:

first limit order = reference price minus configured percentage.

For SHORT:

first limit order = reference price plus configured percentage.

Offset = 0 / Market means the first order is executed as a market order.

### 4. Fixed distribution

With logarithmic distribution disabled, grid prices are evenly distributed across the configured price range.

### 5. % Мартингейла

The nominal value of each next order is:

next nominal = previous nominal × (1 + martingale_percent / 100)

Martingale applies to nominal order value, not raw asset quantity.

For SHORT this distinction is important because asset quantity can decrease while nominal value increases.

### 6. Логарифмическое распределение

Support a configurable logarithmic coefficient.

Required semantics:

- coefficient = 1 → linear/even spacing;
- coefficient > 1 → levels are denser near the current/reference price and more spread toward the far end;
- coefficient < 1 → levels are more spread near the current/reference price and denser toward the far end.

Do not invent an undocumented Veles formula.

Implement a deterministic price-level generator with these exact monotonic density semantics. Keep the mathematical mapping isolated behind a dedicated grid-price-distribution component so it can be replaced if exact Veles implementation details become available.

### 7. Частичное выставление сетки

Support a maximum number of simultaneously active grid orders.

Example:

10 planned levels, active limit = 3.

Only the nearest 3 eligible levels are submitted initially.

When a nearer grid order is executed, the next waiting level becomes eligible for submission.

Waiting levels remain part of GridState.

### 8. Подтяжка сетки

Support a pull-up threshold.

Purpose: if the bot received an entry signal and the first limit order has not executed, but price moves away in the profitable direction, cancel the pending entry/grid and return to waiting for a new entry signal.

LONG:
- if price rises away from the unfilled first limit by the configured pull-up threshold, cancel the pending grid.

SHORT:
- inverse direction.

If first order offset = 0 / Market, Veles treats pull-up as ignored for execution; preserve the configuration field but do not apply pull-up to a market-first entry.

In Backtest, use the existing Veles-compatible bar-close model for pull-up evaluation. Do not use tick data in this task.

## CUSTOM / СВОЙ mode

Allow an explicit ordered list of levels.

Each level contains at minimum:

- offset from reference entry price
- nominal order value

Support LONG and SHORT.

Validate:

- offsets are monotonic in the averaging direction;
- nominal values are positive;
- first level can represent the initial order;
- a single 100% order is valid.

Do not automatically transform a custom grid into Simple-mode parameters.

## SIGNAL / СИГНАЛ mode

Support:

- first order offset = 0 → market;
- first order offset > 0 → limit;
- subsequent DCA orders are market orders;
- every subsequent order requires:
  1. configured Entry/Signal filter event;
  2. minimum price offset from the configured reference.

The reference must support the Veles distinction between:

- offset from previous order;
- offset from initial/reference entry price.

Use the existing Veles Filters/Signals infrastructure from Task №5.

Do not create a second indicator/filter system.

## Position integration

After each executed DCA order:

- increase position quantity;
- recalculate average price using weighted average;
- update realized/unrealized P&L;
- update grid state;
- preserve executed order history.

The formula for average price must be:

sum(quantity_i × price_i) / sum(quantity_i)

For future Exit Engine compatibility, expose the updated average position price as the authoritative TP reference.

## Grid recalculation after averaging

The engine must support recalculation of the remaining grid after a DCA execution.

At minimum:

- mark executed level as filled;
- keep already executed levels immutable;
- preserve remaining planned levels;
- recalculate the eligible/active order set according to partial-grid rules;
- expose the new average position price.

Do not implement the full Exit Engine recalculation yet.

Do not implement Multi-Take, Signal TP, Break-Even, Stop Loss, or Trailing.

## Backtest integration

Extend the existing BacktestBroker / BacktestEngine so that DCA orders can be simulated.

Reuse existing deterministic execution rules.

For this task:

- market orders execute on the next candle OPEN after their signal;
- limit grid orders use the existing deterministic OHLC rule;
- no tick engine;
- no pessimistic wick mode;
- no partial fills.

Do not change existing Task №6 semantics unless required to integrate DCA correctly.

## Strategy integration

DCA/Grid is configuration data attached to the Strategy/StrategyVersion.

The Strategy Engine remains responsible for entry Filters/Signals.

The DCA/Grid Engine is responsible for order-level averaging mechanics after a strategy entry.

Do not put DCA logic inside individual indicators or filters.

## Validation

Unit tests must cover at minimum:

1. SIMPLE LONG grid.
2. SIMPLE SHORT grid.
3. first-order offset.
4. zero offset / market first order.
5. total price coverage / Перекрытие.
6. number of grid levels.
7. linear spacing.
8. logarithmic coefficient = 1.
9. logarithmic coefficient > 1 density direction.
10. logarithmic coefficient < 1 density direction.
11. martingale nominal sizing.
12. martingale with LONG quantity.
13. martingale with SHORT quantity.
14. CUSTOM grid.
15. single-order CUSTOM mode.
16. partial grid submission.
17. submission of next waiting level after fill.
18. pull-up LONG.
19. pull-up SHORT.
20. pull-up ignored for market-first entry.
21. SIGNAL mode first market order.
22. SIGNAL mode first limit order.
23. SIGNAL mode requires signal + minimum offset.
24. SIGNAL mode offset from previous order.
25. SIGNAL mode offset from initial/reference price.
26. weighted average price after DCA.
27. grid state after DCA fill.
28. deterministic backtest repeatability.
29. Task №5 Strategy Engine tests remain green.
30. Task №6 Backtest tests remain green.

## Explicit non-goals

Do NOT implement:

- Multi-Take
- Signal TP
- Minimum P&L exit
- Break-Even
- Stop Loss
- Trailing
- Live trading
- Order recovery
- Risk Manager
- optimizer
- UI redesign
- tick data
- partial fills
- liquidation engine
- autonomous financial parameter tuning

## Validation commands

Run:

- pytest
- ruff check app tests
- npm run build
- git diff --check

Verify:

- no imports from brokers/tinvest inside Strategy/DCA/Backtest core;
- all existing tests pass;
- DCA/Grid remains broker-agnostic;
- one deterministic implementation is used by future Live and Backtest execution layers.

## Commit

Create one focused commit:

feat: implement Veles-compatible DCA Grid engine MVP-4

Do NOT push.

Report:

- implementation summary;
- changed files;
- test count;
- pytest;
- ruff;
- frontend build;
- git diff --check;
- commit SHA;
- blockers only.
