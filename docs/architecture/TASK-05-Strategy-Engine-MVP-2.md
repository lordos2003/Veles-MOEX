# Task №5 — Strategy Engine MVP-2

## Goal

Implement MVP-2 Strategy Engine for Veles-MOEX.

**Primary rule:** reproduce the Veles functional model first. Do not invent a generic trading-rule model where Veles already defines the corresponding behavior. Use the project Veles Help Center engineering reference and the Architecture & Product Specification as authoritative project inputs.

## Scope

Implement only MVP-2:

- Strategy configuration/data model
- Instrument
- Direction: Long / Short
- Entry
- Veles-style Filters / Signals
- Filter arguments
- comparison operators
- crossing operators
- Filter Groups
- calculation methods
- timeframe / interval
- shift
- multi-timeframe active signal state
- initial indicator set
- Entry signal generation
- basic Exit

Do **not** implement DCA/Grid, Martingale, logarithmic distribution, full Multi-Take, Break-Even, Stop Loss, Trailing, live bot execution, or autonomous parameter optimization in this task.

## Veles-compatible Entry model

A comparison Filter is:

Argument 1 → Operator → Argument 2

Arguments may represent:
- templates
- configurable indicators
- signals
- TradingView sources
- partner signals
- constants

A Signal Filter is a distinct filter form and must not be forced into a generic left/operator/right representation.

### Operators

At minimum support the Veles semantics required by MVP-2:
- greater than
- less than
- crossing upward
- crossing downward

Greater/less are persistent state conditions while true.

Crossing operators are event conditions and must fire on the crossing event.

### Filter Groups

Preserve the Veles user model:

- conditions inside one group = AND / И
- groups = OR / ИЛИ

Example:

(A AND B) OR C

Do not expose arbitrary nested AND/OR/NOT trees as the user-facing model.

An internal evaluator abstraction is allowed if it preserves the exact persisted and UI semantics above.

### Calculation method

Support:
1. At bar close
2. Once per minute

Bar-close semantics: a condition met on the closed candle can trigger action on the next candle.

Once-per-minute semantics: evaluate inside the current candle once per minute.

### Timeframe and signal state

Filter arguments can have their own timeframe/interval and supported parameters such as period, method and shift.

Implement active signal state for higher timeframes: a higher-timeframe condition can remain active during its timeframe interval and combine with lower-timeframe conditions.

Do not implement entry evaluation as a stateless check of only the current candle.

## Initial indicators

Implement the MVP-2 indicator interfaces and the initial set:

- RSI
- SMA
- EMA
- MACD
- Bollinger Bands
- ATR
- CCI
- Williams %R
- CMO
- MFI
- Stochastic
- ADX

The indicator library must be extensible without changing Strategy Engine code.

## Architecture constraints

- Strategy Engine must be broker-agnostic.
- No T-Invest-specific logic inside Strategy Engine.
- Entry Engine produces a trading signal/decision; it does not submit broker orders.
- Preserve strategy-version reproducibility.
- Use the existing project architecture and existing Task №1–4 code.
- Do not modify completed read-only broker/account/position/order/deal functionality unless required by a concrete integration issue.
- Do not tune financial parameters.
- Do not add features outside this task.

## Expected implementation

Create clean domain models/services for:

- Strategy
- StrategyVersion
- Entry configuration
- Filter
- Filter Group
- Filter Argument
- Operator
- Signal state
- Indicator definitions/configuration
- Entry evaluation result / trading signal

Provide deterministic unit tests covering at least:

1. A > B
2. A < B
3. crossing upward
4. crossing downward
5. two conditions inside one group = AND
6. two groups = OR
7. mixed example (A AND B) OR C
8. bar-close calculation timing
9. once-per-minute calculation timing
10. higher-timeframe active signal state combined with lower-timeframe condition
11. Long and Short direction
12. indicator configuration with timeframe/period/shift

If the existing repository already has related abstractions, adapt them rather than duplicating them.

## Validation

Run the existing test suite and all relevant lint/type/build checks.

The implementation is complete only when:
- tests pass;
- existing Task №1–4 functionality remains intact;
- the Strategy Engine is independent of T-Invest;
- the persisted model and evaluation semantics match the Veles model described above.

## Commit

Create one focused commit:

feat: implement Veles-compatible strategy engine MVP-2

Do not implement later MVP items in this task.
