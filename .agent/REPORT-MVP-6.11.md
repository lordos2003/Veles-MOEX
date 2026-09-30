# Veles-MOEX — REPORT: MVP-6.11 Bot Deposit Sizing & Entry from Confirmed Flat

## Implementation commits

1. `e036c0e74e8ac50f6d4b2bd82842c0a90b845120` — "feat: implement MVP-6.11 bot
   deposit sizing and entry from confirmed flat" (implementation on
   `agent/review/mvp-6.11`).

- Base before MVP-6.11: `master @ 10d445e0af61c617d7484ca38d79a94cb45b0aa0`
  (contains the accepted MVP-6.10, merge `14168ca798c00b8a28ef278bb245391a07bce958`).
- Review branch implementation HEAD: `e036c0e74e8ac50f6d4b2bd82842c0a90b845120`.
- No changes to `master`; publication requires independent acceptance first.

## Objective

Close the two remaining blockers of the live strategy path:

1. **Sizing** — `SizingNotConfigured`: no authoritative position-sizing source
   existed. The approved contract makes the **bot deposit** (a *bot* setting
   from the Veles "Full list of bot settings", "The amount within which the bot
   trades") the sizing source and defines the deposit -> base nominal
   conversion (C2) and the MOEX lot rounding contract (C3).
2. **Flat entry** — the MVP-6.9 gate blocked *all* live intents unless a
   resolvable non-zero position existed, so a confirmed flat position could
   never start a deal. The approved contract (C4) makes the live position
   state three-valued and allows entry only from a **confirmed flat** position.

## What was implemented

### C1. Deposit is a bot setting (Veles "Full list of bot settings")

- `backend/app/models/bot.py`: `Bot.deposit: Mapped[Decimal | None]`
  (`Numeric(20, 8)`, nullable) — a **bot** field, not a `StrategyVersion`
  field (the Veles Help Center lists the bot deposit among the bot-level
  settings, separate from the strategy settings).
- `backend/alembic/versions/0004_bot_deposit.py`: migration `0004_bot_deposit`
  (adds the column; single Alembic head, chain verified).
- `backend/app/bots/schemas.py`: `BotResponse.deposit` (read) and
  `BotDepositUpdate` (write) with `deposit: Decimal | None = Field(gt=0)` —
  a non-positive value is rejected (FastAPI 422), `None` clears. No default
  deposit is invented.
- `backend/app/bots/repository.py`: `update_deposit(bot, deposit)`.
- `backend/app/api/bots.py`: `GET /api/bots/{id}` exposes `deposit`;
  `PATCH /api/bots/{id}` sets/clears it (404 for an unknown bot; 422 for a
  non-positive value).
- Frontend: no bot form exists; no UI change was required (build stays green).
- An unset deposit (`None`) keeps the existing `SizingNotConfigured` behavior
  for the live cycle (no meaning change).

### C2. Deposit -> base nominal (one broker-neutral function)

`backend/app/trading/sizing.py:deposit_to_base_nominal(deposit, dca_grid)`:

- **SIMPLE**: `n = dca_grid.levels`, `k = 1 + martingale/100` (`k = 1` when
  martingale is off), `first_nominal = D / sum(k**i, i=0..n-1)`; level `i`
  nominal = `first_nominal * k**i` — the existing `DCAGridEngine` martingale
  math is unchanged, only the base nominal is derived from `D`, so the sum of
  the nominals of all grid orders of one deal (first order included) equals
  the deposit.
- **CUSTOM**: level nominal = `D * nominal_percent / 100` (the existing
  `_build_custom` math with `base_nominal = D`); when the level percentages
  sum to more than 100 the deal would exceed the deposit: explicit
  `CustomDepositExceeded`.
- **SIGNAL**: the existing SIGNAL engine does **not** use
  `DCAGridConfig.levels` as a maximum order-count limit (subsequent averaging
  orders in `signal_dca_order` are unbounded), so **no limit is invented**:
  live SIGNAL sizing blocks with an explicit `SignalSizingUnsupported`
  (documented gap, pending a separately approved contract).
- Spot semantics only: the deposit is used 1:1. No leverage/margin field
  exists in the configuration (the Veles bot-settings list contains none) and
  none is added. No FX conversion: the deposit currency is the instrument's
  trading/price currency.
- `PositionSizing` now carries `deposit`, `lot_size` and `currency`;
  `resolve_base_nominal(dca_grid)` applies C2. The MVP-6.8 `base_nominal`
  path and the `SizingNotConfigured` semantics are unchanged.

### C3. MOEX lot rounding (project contract, not a Veles rule)

`backend/app/trading/sizing.py:round_grid_to_lot(grid, lot_size, currency)`:

- Order quantity in units = nominal / order_price, rounded **down** to a whole
  number of lots (`lot_size` from the instrument).
- If **any** order of the deal rounds to 0 lots, the **whole entry** is
  blocked with `SizingBelowLot` naming the level, its nominal, price and lot
  size; no partial grid is submitted; the unused remainder of the deposit
  after rounding stays unused (no redistribution).
- A missing/non-positive `lot_size` or an unresolvable instrument currency
  blocks the entry explicitly (`LotSizeUnavailable` / `CurrencyUnavailable`);
  no default lot or currency is substituted.
- `GridOrder` (a plan data carrier in `app/strategies/domain.py`) now carries
  the planned `nominal`; `StrategyEngine.evaluate()` populates it. No
  DCA/Grid mathematics changed.
- Applied in `TradingEngine.process()` on the live FLAT entry path only;
  Backtest and the DCA engine are untouched.

### C4. Confirmed-flat entry (three-valued position state)

- `backend/app/trading/position_manager.py`: `LivePositionState`
  (`UNKNOWN` / `FLAT` / `OPEN` / `SIGN_MISMATCH`), `PositionManager`
  reconciliation tracking (`mark_reconciled()`, `invalidate_reconciliation()`,
  `position_state(figi, direction)`). The state is established **only** by a
  successful broker position reconciliation; restored (durable) positions from
  a snapshot are **not** a confirmation (`load_state` resets to UNKNOWN);
  fill-driven position changes keep the state updated afterwards
  (Architecture & Product Specification section 8).
- `backend/app/trading/recovery.py`: `LiveRecoveryCoordinator.recover()` calls
  `mark_reconciled()` after applying `get_open_positions` facts (stale local
  positions are dropped first) and `invalidate_reconciliation()` when that
  call fails.
- `backend/app/trading/engine.py` gating (per the approved contract):
  | State | Live intents |
  |---|---|
  | `UNKNOWN` (never reconciled / reconciliation failed / stale) | none (MVP-6.9 behavior preserved) |
  | `FLAT` (successful reconciliation confirmed zero/no position) | entry only — no exit intents; blocked while the bot has active (non-terminal) orders |
  | `OPEN` (reconciled non-zero, sign matching) | exits only (real quantity via `resolve_quantity`); no new grid/entry intents from a fresh evaluation |
  | sign mismatch | none |
- Entry precondition (FLAT): the bot must have **no active (non-terminal)
  orders** in the OrderManager (correlated by `bot_id`); otherwise re-entering
  on every cycle while a limit first order / grid is still working is
  prevented. `TradingEngine` gains `bot_id` for the correlation; when the bot
  cannot be correlated (no `bot_id`) the entry is blocked (the precondition
  cannot be verified; no fabricated safety assumption).
- The MVP-6.9 invariants are preserved: the PositionManager remains the only
  authoritative live quantity source; an unknown/unresolved state still
  blocks all live intents.

### C5. Production wiring

- `backend/app/trading/live_execution.py`: the per-bot engine factory wires
  `PositionSizing(deposit=Bot.deposit, lot_size=Instrument.lot_size,
  currency=Instrument.currency)` and `bot_id` into the per-bot
  `TradingEngine`. T-Invest stays read-only: no `place_order`/transport code
  was changed and no live order submission is enabled.
- `backend/app/trading/__init__.py`: public exports for the new sizing types,
  `LivePositionState`, `deposit_to_base_nominal` and `round_grid_to_lot`.
- Documentation: `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` section 29
  (MVP-6.11) records C1–C5, the sources and the boundaries.

## Architecture decisions / boundaries

- The sizing/rounding contracts live in the broker-neutral
  `app/trading/sizing.py` (no broker import); `DCAGridEngine` mathematics,
  Veles Filter/Signal semantics and Backtest behavior are unchanged.
- Deposit is 1:1 spot usage; the absence of any leverage/margin field in the
  Veles bot-settings list is itself the source that no such field is added.
- SIGNAL mode is **blocked** (explicit error) rather than sized with an
  invented order-count limit (approved C2 contract).
- Cross-cycle deal continuation / grid state persistence is out of scope
  (separate MVP): while OPEN, no new grid/entry intents are submitted from a
  fresh evaluation.
- The periodic live-cycle scheduler is not part of this MVP (the strategy
  cycle is still invoked explicitly via `BotRuntime.execute_strategy`).
- Known documentation gap: `PROJECT_STATE.md` (MVP-6.8 paragraph) still says
  "T-Invest is read-only; no live order submission is enabled", while the
  MVP-6.2 section describes the Open API `place_order` path used by the
  OrderManager. The execution path via `RiskManager -> OrderManager ->
  BrokerAdapter.place_order` is the existing accepted architecture; this MVP
  does not change it and does not enable any new submission surface. The
  wording reconciliation is left to the control-branch documentation owner.
- Known boundary (backtest): the Backtest path sizes orders from its own
  `BacktestConfig` and does not use the bot deposit; the Veles backtest sizing
  semantics are not defined in the documentation inspected, so no backtest
  deposit rule is invented.

## Tests

`backend/tests/test_mvp611_deposit_sizing.py` (30 focused tests) maps to the
approved test list:

1. SIMPLE: `D=10000, n=3, martingale=20%` -> nominals `2747.25…`,
   `3296.70…`, `3956.04…` and sum == D within Decimal precision
   (`test_simple_deposit_split_with_martingale`);
2. SIMPLE without martingale -> equal nominals `D/n`
   (`test_simple_deposit_split_without_martingale_is_equal`);
3. CUSTOM: nominal = `D * nominal_percent/100`; sum of percentages > 100 ->
   explicit `CustomDepositExceeded` (`test_custom_deposit_split_by_percent`,
   `test_custom_percent_sum_over_100_is_blocked`);
4. SIGNAL: explicit `SignalSizingUnsupported` (the engine does not use
   `levels` as a limit; no limit invented)
   (`test_signal_sizing_is_blocked_with_explicit_error`);
5. Sizing function independent of `DCAGridEngine` math; `GridOrder` carries
   the nominal (`test_sizing_function_is_independent_of_grid_engine_math`,
   `test_grid_order_carries_nominal_into_plan`);
6. Lot rounding down; a level below one lot blocks the **whole entry** with
   the level/nominal/price/lot-size in the error message
   (`test_lot_rounding_down_to_whole_lots`,
   `test_level_below_one_lot_blocks_the_whole_entry`,
   `test_flat_entry_blocked_when_below_lot`);
7. Missing lot size / instrument / currency block explicitly
   (`test_missing_lot_size_blocks`, `test_missing_currency_blocks`,
   `test_flat_entry_blocked_when_lot_size_unavailable`,
   `test_flat_entry_blocked_when_currency_unavailable`);
8. `Bot.deposit` None/0/negative -> `SizingNotConfigured`; API validation
   (422 for non-positive, persist/clear via `PATCH`)
   (`test_deposit_none_zero_negative_raises_sizing_not_configured`,
   `test_position_sizing_deposit_applies_c2`,
   `test_position_sizing_base_nominal_path_unchanged`,
   `test_bot_deposit_schema_validation`,
   `test_bot_deposit_api_endpoint_validation`,
   `test_repository_update_deposit_persists_value`);
9. `UNKNOWN` -> no intents at all (MVP-6.9 regression)
   (`test_unknown_position_state_blocks_all_intents`);
10. `FLAT` (after a successful reconciliation) + no active orders -> entry
    intents submitted via the Risk Manager, lot-rounded quantities
    (`test_flat_without_active_orders_allows_entry`,
    `test_flat_entry_quantities_round_down_to_lots`);
11. `FLAT` + active bot orders -> no entry; re-entry after the order is
    terminal (`test_flat_with_active_bot_orders_blocks_entry`,
    `test_flat_after_active_order_filled_allows_entry`,
    `test_flat_entry_blocked_when_bot_cannot_be_correlated`);
12. Absent position without a successful reconciliation -> `UNKNOWN`
    (fills and snapshot restore do not establish the state; a failed
    reconciliation invalidates it)
    (`test_absent_position_without_successful_reconciliation_is_unknown`);
13. `OPEN` -> no new grid/entry intents; exits unchanged (MVP-6.9 regression)
    (`test_open_position_submits_exit_only`);
14. Sign mismatch -> no intents (`test_sign_mismatch_blocks_all_intents`);
15. Backtest suite unchanged (`test_backtest_style_evaluate_unchanged`).

Existing tests were updated only where the approved contract changed the
behavior:

- `tests/test_mvp69_position_state.py`: the two tests that expect a live exit
  order now establish the OPEN state with an explicit
  `PositionManager.mark_reconciled()` (the state contract, not the exit
  math, changed).
- `tests/test_mvp610_market_snapshot.py::test_position_invariant_valid_snapshot_and_position`:
  OPEN now submits the exit only (no new grid entry while OPEN) — the
  assertion changed from 2 orders (grid BUY + exit SELL) to 1 (exit SELL).
- `tests/test_trading_risk.py::test_trading_engine_process_routes_through_risk`:
  the strategy-config stub now carries a real `DCAGridConfig` (the engine
  reads `dca_grid` for the C2 conversion).

## Commands / results

- `pytest` (backend, full suite): **403 passed, 1 skipped** (was 373 passed,
  1 skipped; +30 new tests; the single skip is the opt-in live sandbox
  integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `npm run build` (frontend): **built successfully** (no frontend changes).
- `alembic heads`: single head `0004_bot_deposit` (chain
  `0001_initial -> 0002 -> 0003 -> 0004_bot_deposit`).
- Diff review against the merge-base (`10d445e`): 18 files; no changes to
  `app/strategies/dca_grid.py`, `app/backtest/`, `app/brokers/`,
  `app/strategies/filters.py`, `app/strategies/entry.py`,
  `app/strategies/exit.py` or `app/trading/plan_intent.py` (the prohibited
  zones and the existing intent conversion are untouched).

## Git state

- Implementation branch `agent/review/mvp-6.11` -> `e036c0e74e8ac50f6d4b2bd82842c0a90b845120`
  (base `master @ 10d445e0af61c617d7484ca38d79a94cb45b0aa0`), pushed to
  `origin` on 2026-09-29 on the owner's explicit instruction.
- `agent/control` contains this report (pushed to `origin` on the same
  instruction).
- `master` unchanged (`10d445e`); no merge into `master` has been performed.
  Publication requires independent acceptance first.

## Known limitations / boundaries

- SIGNAL mode live sizing is blocked (no order-count limit invented).
- Cross-cycle deal continuation / grid state persistence: not implemented
  (separate MVP); while OPEN the cycle submits exits only.
- No periodic live-cycle scheduler in this MVP (cycle triggered explicitly).
- Backtest sizing does not use the bot deposit (Veles backtest sizing
  semantics undefined in the inspected documentation; no rule invented).
- Exit TP price is still derived from the market-context reference price (the
  pre-existing MVP-6.9 boundary), unchanged by this MVP.

## Documentation / specification gaps (recorded per the task, not fixed here)

- **Live/Backtest sizing contracts differ.** Backtest sizing uses
  `BacktestConfig.quantity` (first-order units, default `1`,
  `backend/app/backtest/config.py:30`, consumed at
  `backend/app/backtest/engine.py:90`) while Live now uses the deposit
  contract C2 (`Bot.deposit` -> `deposit_to_base_nominal`). Aligning them
  requires a separate task (spec principle: Backtest and Live share trading
  logic).
- **`PROJECT_STATE.md` wording vs the execution path.** `PROJECT_STATE.md`
  (MVP-6.8 paragraph) says "T-Invest is read-only; no live order submission
  is enabled", while `TInvestAdapter.place_order()` (PostOrder, MVP-6.2)
  exists and the OrderManager uses it. Clarification: the adapter/method is
  **implemented** (MVP-6.2, accepted) but real order submission is **not
  enabled in the production live runtime** by this MVP — MVP-6.11 produces
  risk-gated intents only, through the existing accepted
  `RiskManager -> OrderManager -> BrokerAdapter` path, and changes no
  `place_order`/transport code. The wording reconciliation belongs to the
  control-branch documentation owner; it is not changed here.

## AGENTS.md compliance

- Only the requested scope was implemented (C1–C5 + §29 + the 15 test
  contracts); no refactors, no unrelated changes, no speculative features.
- `DCAGridEngine` mathematics, Veles Filter/Signal semantics, Backtest
  behaviour, `Decimal`/UTC handling and broker neutrality are unchanged
  (verified by the diff review and the unchanged existing suites).
- T-Invest stays read-only in the live runtime: this MVP produces risk-gated
  intents; no production order submission is enabled (no
  `place_order`/transport changes).
- No invented defaults: deposit, lot, currency, max order count, leverage
  (the SIGNAL gap is blocked, not defaulted).
- Everything not covered by C1–C5 stops at the boundary and is documented in
  this REPORT (SIGNAL block, deal continuation, live-cycle scheduler,
  backtest deposit gap, PROJECT_STATE wording).
- The REPORT is written to `agent/control` before any publication; no
  self-declared acceptance; no merge into `master`.

## Review request

Ready for independent ChatGPT review on `agent/review/mvp-6.11`
(`e036c0e74e8ac50f6d4b2bd82842c0a90b845120` against base
`10d445e0af61c617d7484ca38d79a94cb45b0aa0`). No merge into `master` has
been performed; publication requires acceptance first.
