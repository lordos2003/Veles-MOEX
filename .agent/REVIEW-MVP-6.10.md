# Veles-MOEX — Independent Review: MVP-6.10

## Verdict

**REJECTED — corrections required before acceptance**

Reviewed implementation:
`4c4e8fa1c30d2cedc5eef4c1bb81fff643a9d88d`

Base:
`master @ cdc10296e32509f2d716c85c1b58e62a9b01b2cf`

## Blocking finding

### 1. Self-defined indicator warmup rules

`backend/app/strategies/config.py` introduces:

- `_INDICATOR_WARMUP_BARS`
- `_argument_required_bars()`
- `_groups_required_bars()`
- `required_bars()`

The implementation contains rules such as:

- SMA = 20
- EMA = 9
- RSI = 14
- ADX = 28
- MACD = slow + signal

These are implementation assumptions about the amount of historical data required by Veles indicators. They are not established by the Veles documentation as a universal warmup contract.

The official Veles documentation defines each flexible indicator through its own parameters (period/length, interval, coefficients or additional parameters, method and shift). The flexible-indicator documentation does not define a universal `required_bars` algorithm.

Therefore MVP-6.10 must not introduce an independent indicator-history calculation that can diverge from Veles semantics.

## Required correction

Remove the self-defined indicator warmup table and the derived universal `required_bars` algorithm from MVP-6.10.

The market snapshot layer must not invent indicator semantics.

The corrected MVP should obtain only the market data required by an explicitly defined, already-supported Veles strategy contract. If determining the exact required history for a particular indicator requires additional Veles specification, that specification must be established first rather than inferred.

## Additional review observation

The REPORT states that multi-timeframe filter arguments remain a follow-up limitation. This is acceptable only if the current MVP explicitly does not claim full support for Veles filters using different argument intervals.

Do not silently evaluate such filters against the bot timeframe.

## What is acceptable in the current implementation

- broker-neutral `MarketSnapshot` boundary;
- real broker market data;
- `Decimal` prices;
- UTC timestamps;
- explicit per-bot timeframe;
- explicit blocking on missing/invalid snapshot;
- preservation of the MVP-6.9 position-state gate;
- separation of live market data from Backtest;
- no T-Invest order submission.

## Acceptance conditions

MVP-6.10 can return for review after:

1. removal of the self-defined indicator warmup rules;
2. removal/refactoring of `required_bars` so it does not invent Veles indicator semantics;
3. tests updated accordingly;
4. full test suite, lint and build rerun;
5. new implementation REPORT committed to `agent/control`;
6. `master` remains unchanged.

**No publication to master.**
