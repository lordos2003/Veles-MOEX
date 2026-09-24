# Veles-MOEX — REPORT: MVP-6.9 Position State & Authoritative Quantity

## Implementation commits

1. `5acc7a78d1159b134b9a3a6e0c0a3b9c114404be` — "feat: implement MVP-6.9 position
   state and authoritative quantity" (initial implementation on
   `agent/review/mvp-6.9`).
2. `5b4c42b` — "fix: block all live intents when position state is unresolved
   (MVP-6.9 review blocker)" (focused correction, see "Review blocker fix"
   below).

- Base: `master @ b2c4ee2` (current accepted master).
- Review branch HEAD: `5b4c42b` (published to `origin/agent/review/mvp-6.9`).
- `master` NOT modified; no merge/rebase.

## Objective

Eliminate the live-execution quantity boundary left by MVP-6.8: the
`position_qty=1.0` placeholder is removed and the Position Manager becomes the
only authoritative source of live execution quantity.

## Review blocker fix (commit `5b4c42b`)

Reviewer correction `b841f16 control: add MVP-6.9 review blocker correction`
changed requirement 8 from "no live **exit** order" to "no live **order**" and
added "Sign-inconsistent position: no live order".

**Blocker:** `TradingEngine.process()` mapped `PositionUnavailable` /
`InvalidPositionQuantity` to `position_qty=None`, but `StrategyEngine.evaluate()`
still built DCA/Grid orders from the explicit `base_nominal`, and
`plan_to_intents()` converted them — so with an absent/zero/sign-mismatched
position a live Grid order could still be produced.

**Fix (commit `5b4c42b`):** `TradingEngine.process()` now returns the plan
immediately, **without creating or submitting any ExecutionIntent**, when the
position state is unresolved. `backend/app/trading/engine.py`:

- New `TradingEngine._position_gates_execution(position_qty) -> bool`: returns
  `True` only for a live per-bot engine (`instrument_figi` set) when
  `position_qty is None` (missing / zero / sign-mismatch). Generic/Backtest
  engines (no `instrument_figi`) are not gated.
- In `process()`, after `evaluate(...)` and before intent
  creation/submission: `if self._position_gates_execution(position_qty):
  return plan`.
- `_exit_position_quantity()` docstring updated to reference the gate.

Regression tests proving `OrderManager.list_orders() == []` for absent, zero,
and sign-mismatched positions (see "Tests" below).

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

`backend/tests/test_mvp69_position_state.py` (12 focused tests):

1. valid real position resolves quantity;
2. missing position -> `PositionUnavailable`;
3. `quantity == 0` -> `InvalidPositionQuantity`;
4. negative / sign-mismatched quantity -> `InvalidPositionQuantity` (and a SHORT
   position is valid for a SHORT strategy);
5. real quantity reaches ExitPlan;
6. real quantity reaches ExecutionIntent;
7. **no live order at all** when the position is absent
   (`OrderManager.list_orders() == []`);
8. **no live order at all** when the position quantity is zero
   (`OrderManager.list_orders() == []`) — regression test added by the blocker
   fix;
9. **no live order at all** when the position is sign-mismatched (short
   position vs LONG strategy, `OrderManager.list_orders() == []`) — regression
   test added by the blocker fix;
10. no fallback quantity (exit quantity is the real position quantity);
11. Backtest-style `evaluate(config, context)` is unchanged (no error, no exits);
12. DCA/Grid still builds from the explicit base nominal.

Existing tests were updated only where behavior intentionally changed:
- `tests/test_entry_engine.py::test_strategy_engine_plan_entry_and_exit` now
  passes `position_qty=Decimal("2")`.
- `tests/test_mvp68_market_context_sizing.py` and
  `tests/test_strategy_live_integration.py` placeholder-exit tests now verify a
  **non-positive** exit quantity is not converted (the `1.0` placeholder boundary
  is superseded by MVP-6.9).

## Commands / results

- `pytest`: **348 passed, 1 skipped** (was 336 passed, 1 skipped; +12 new
  tests — 10 from the initial implementation and 2 added by the blocker fix;
  the single skip is the opt-in live sandbox integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `npm run build`: **✓ built in 8.63s**.

## Git state

- Review branch `agent/review/mvp-6.9` -> `5b4c42b` (published).
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


## ChatGPT acceptance / publication

- Independent ChatGPT review: **ACCEPTED**.
- Acceptance: 2026-09-24.
- Pull Request: #2 — `MVP-6.9: Position State & Authoritative Quantity`.
- Published to `master` by merge commit `cdc10296e32509f2d716c85c1b58e62a9b01b2cf`.
- Review branch head before publication: `5b4c42be4d49d700e8750315c1da81b17bc04a1d`.
- `master` now contains the accepted MVP-6.9 implementation.
- No further merge/push is required for MVP-6.9.
