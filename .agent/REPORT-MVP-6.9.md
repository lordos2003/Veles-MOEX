# Veles-MOEX — REPORT: MVP-6.9 Position State & Authoritative Quantity

## Implementation commit

`5acc7a78d1159b134b9a3a6e0c0a3b9c114404be` — "feat: implement MVP-6.9 position
state and authoritative quantity" (single focused commit on
`agent/review/mvp-6.9`).

- Base: `master @ b2c4ee2` (current accepted master).
- Review branch HEAD: `5acc7a7` (published to `origin/agent/review/mvp-6.9`).
- `master` NOT modified; no merge/rebase.

## Objective

Eliminate the live-execution quantity boundary left by MVP-6.8: the
`position_qty=1.0` placeholder is removed and the Position Manager becomes the
only authoritative source of live execution quantity.

## What was implemented

### 1. PositionManager as the only authoritative quantity source
`backend/app/trading/position_manager.py`

- Added broker-neutral domain exceptions `PositionUnavailable` and
  `InvalidPositionQuantity`.
- Added `PositionManager.resolve_quantity(instrument_figi, direction) -> Decimal`:
  - raises `PositionUnavailable` when no position exists for the FIGI;
  - raises `InvalidPositionQuantity` when the position quantity is `0` or whose
    sign is inconsistent with the strategy direction (e.g. a LONG strategy
    holding a short position);
  - otherwise returns the positive position magnitude. **No fabricated/default
    quantity is ever returned.**
- Positions are obtained through the broker-neutral adapter
  (`BrokerAdapter.get_open_positions`) during the existing recovery
  reconciliation (`LiveRecoveryCoordinator`), which feeds `PositionManager`. The
  broker is never queried inside StrategyEngine, ExitEngine, BotRuntime or
  OrderManager (authoritative path preserved).

### 2. Remove `position_qty=1.0` from the live path
`backend/app/strategies/engine.py`

- `StrategyEngine.evaluate(..., position_qty=None)` now builds exit plans only
  when a real, positive `position_qty` is supplied; the hardcoded
  `position_qty=1.0` is removed from the live path. Without a real quantity no
  exits are planned (no position / zero / sign-mismatch => no live exit).

### 3. Live path resolves the real quantity
`backend/app/trading/engine.py`

- `TradingEngine` gained a per-bot `instrument_figi`.
- `process()` resolves the real exit quantity via
  `PositionManager.resolve_quantity(self._instrument_figi, direction)` and passes
  it to `evaluate`. `PositionUnavailable`/`InvalidPositionQuantity` are caught and
  mapped to `position_qty=None` (no live exit order).
- Broker-neutral `Direction` is used; the broker/position DTOs never leak.

### 4. ExitPlan -> ExecutionIntent conversion
`backend/app/trading/plan_intent.py`

- `plan_to_intents()` now converts exit plans into `ExecutionIntent`s when they
  carry a positive real quantity; non-positive quantities are skipped.
- Grid intents keep a deterministic content-hash id (`plan-…`); exit intents get
  a distinct deterministic id (`exit-…`), preserving idempotency semantics.

### 5. Wiring
`backend/app/trading/live_execution.py`

- The per-bot `TradingEngine` is created with `instrument_figi=instrument.figi`
  so `process()` can resolve the position quantity. The wired `PositionManager`
  is documented as the authoritative quantity source.

### 6. Documentation
`docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` — added section 27
(Position state & authoritative quantity) and corrected the MVP-6.8 exit note.

## Architecture decisions / boundaries

- The authoritative path is
  `T-Invest -> BrokerAdapter -> PositionManager -> real position quantity ->
  Exit/Strategy planning -> ExitPlan -> ExecutionIntent -> RiskManager ->
  OrderManager`. PositionManager is never bypassed by reading the broker
  directly inside StrategyEngine/ExitEngine/BotRuntime/OrderManager.
- Exit quantity is the position magnitude (`abs`); the exit side is derived from
  `direction` by the existing Exit Engine (no exit-mode redesign).
- T-Invest stays read-only; no actual live order submission is added.
- Note: the live strategy path still requires an explicit sizing source
  (`SizingNotConfigured`) and a market-data source for entry evaluation — those
  remain the documented MVP-6.8 boundaries and are not part of MVP-6.9.

## Explicit confirmation: no fabricated/default live quantity remains

`git grep "position_qty=1[.0]*"` on the product code finds only comments/docs
and a legitimate `on_average(position_qty=10.0)` test fixture. There is **no
`position_qty=1.0` placeholder in the live path** and no fabricated/default
quantity anywhere in the exit planning or intent generation.

## Tests

`backend/tests/test_mvp69_position_state.py` (10 focused tests):

1. valid real position resolves quantity;
2. missing position -> `PositionUnavailable`;
3. `quantity == 0` -> `InvalidPositionQuantity`;
4. negative / sign-mismatched quantity -> `InvalidPositionQuantity` (and a SHORT
   position is valid for a SHORT strategy);
5. real quantity reaches ExitPlan;
6. real quantity reaches ExecutionIntent;
7. no live exit order when the position is absent;
8. no fallback quantity (exit quantity is the real position quantity);
9. Backtest-style `evaluate(config, context)` is unchanged (no error, no exits);
10. DCA/Grid still builds from the explicit base nominal.

Existing tests were updated only where behavior intentionally changed:
- `tests/test_entry_engine.py::test_strategy_engine_plan_entry_and_exit` now
  passes `position_qty=Decimal("2")`.
- `tests/test_mvp68_market_context_sizing.py` and
  `tests/test_strategy_live_integration.py` placeholder-exit tests now verify a
  **non-positive** exit quantity is not converted (the `1.0` placeholder boundary
  is superseded by MVP-6.9).

## Commands / results

- `pytest`: **346 passed, 1 skipped** (was 336 passed, 1 skipped; +10 new tests;
  the single skip is the opt-in live sandbox integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `npm run build`: **✓ built in 3.06s**.

## Git state

- Review branch `agent/review/mvp-6.9` -> `5acc7a7` (published).
- `master` unchanged at `b2c4ee2`; no merge/rebase; working tree clean.
- `agent/control` updated with this report only.

## Known limitations / boundaries

- The live strategy path still requires an explicit position-sizing source
  (`SizingNotConfigured`) and a market-data/candle source to evaluate entry
  filters — documented MVP-6.8 boundaries, not addressed by MVP-6.9.
- Exit TP price is still derived from the market-context reference price, not
  the position average price; MVP-6.9 makes only the quantity authoritative.
- `PositionManager` is populated from broker facts during recovery; there is no
  live order submission/position streaming in this MVP (read-only).
