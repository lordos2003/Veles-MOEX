# Veles-MOEX — REPORT: MVP-6.12 Live Deal Continuation (Simple TP, Simple/Custom grid)

## Implementation commits

1. `a4f792d39f12f2db7b88ce64ae3ed766e9200660` — "feat: implement MVP-6.12
   live deal continuation (simple TP, simple/custom grid)" (implementation on
   `agent/review/mvp-6.12`).

- Base before MVP-6.12: `master @ 59a38974cd27405f40332806fee7dfa8fabc569e`
  (contains the accepted MVP-6.11, merge `40cf6ce`).
- Review branch implementation HEAD: `a4f792d39f12f2db7b88ce64ae3ed766e9200660`.
- No changes to `master`; publication requires independent acceptance first.
- GitHub Issue #7 stays **open** (not closed by this implementation; only an
  independent acceptance + publication closes it).

## Objective

After MVP-6.11 the live path can **open** a deal from a confirmed FLAT, but
cannot **conduct** one: the TP came from `StrategyEngine.evaluate()` at the
market price only when the entry signal fired again, averaging fills did not
recalculate anything, grid limit prices were not tick-aligned (the
`TInvestAdapter` rejects non-multiple prices), and no durable deal state
existed to reconcile after a restart. MVP-6.12 brings the Backtest-style deal
semantics to Live, event-driven by broker fills, per the owner-approved
contracts D1–D6 (2026-09-30).

## What was implemented

### D1. Supported configuration, rejected at START

- `backend/app/trading/deal.py:validate_live_deal_config(config)` — live deal
  continuation applies only when `DCAGridConfig.mode ∈ {SIMPLE, CUSTOM}`,
  `ExitConfig.take_profit.kind == "fixed_percentage"`, `stop_loss is None`,
  `signal_stop is None` and `pull_up_percent == 0`. Anything else raises
  `DealConfigUnsupported` with the explicit reason (Multi-Take, Signal TP,
  break-even, stop-loss, signal stop, pull-up, SIGNAL grid mode).
- Wired at the composition boundary in
  `backend/app/trading/live_execution.py` (the per-bot engine factory), so the
  rejection happens at bot START.
- `backend/app/api/bots.py:_apply` maps `DealConfigUnsupported` to HTTP 409
  ("config not supported for live deal continuation: ...") and persists the
  actual runtime state (ERROR) — no silent fallback, no invented default.

### D2. Deal lifecycle (event-driven by fills)

- New broker-neutral domain `backend/app/trading/deal.py`: `Deal` /
  `DealLevel` / `DealStatus` (`OPENING` / `OPEN` / `CLOSING` / `CLOSED` /
  `ERROR`) / `DealLevelStatus` (`waiting` / `active` / `filled` / `cancelled`),
  the `DealError` family (`DealBlocked`, `DealOrderRejected`,
  `DealTickSizeInvalid`, `DealPositionContradiction`,
  `DealReconciliationRequired`, `DealConfigUnsupported`) and the D3 helpers.
  `Decimal` only; `datetime` is timezone-aware UTC (`utcnow()`).
- Persistence: `backend/app/models/deal.py` (+ `DealLevel`), migration
  `backend/alembic/versions/0005_deal_continuation.py` (single head,
  `0005_deal_continuation`, `down_revision = 0004_bot_deposit`),
  `backend/app/persistence/deal_store.py` (`DealStore` protocol,
  `SqlAlchemyDealStore`, `InMemoryDealStore` for tests).
- `backend/app/trading/deal_manager.py` (`DealManager`):
  - Open (from the MVP-6.11 FLAT entry path): the full grid is built once from
    the snapshot price (`DCAGridEngine`, per-level `base_nominal` = deposit
    split per C2), C3 (lot rounding) + D3 (tick alignment) are applied to
    **every** level; any failure blocks the whole entry. The Deal is persisted
    **before** any order is submitted; then the first order plus up to
    `active_limit` active levels are placed. Intent ids are deterministic
    (`deal-{id}-grid-{index}` / `deal-{id}-tp-{rev}`).
  - Entry fill → Deal OPEN → TP placed (D4).
  - DCA fill (partial or full) → level state updated, TP re-armed (D4), next
    waiting level(s) placed so the active count stays at `active_limit`.
  - TP partial fill → the TP keeps working; position reaches zero → remaining
    grid orders cancelled → Deal CLOSED → the cycle returns to the FLAT entry
    path for the next deal.
  - The deposit is captured on the Deal at entry (MVP-6.11 C6); later deposit
    edits affect only the next Deal.
- Fill routing: `OrderManager` gains a synchronous `fill_listener`
  (`backend/app/trading/order_manager.py`); `DealManager` registers it and
  queues fills, `pump()` (async) drains them. Production wires `pump` as the
  optional per-batch `on_event` hook of `TInvestStreamManager`
  (`backend/app/brokers/tinvest_streams.py`) — no broker type enters the deal
  layer; correlation is `bot_id` + deterministic intent ids.

### D3. Tick rounding (safe direction, Decimal only)

- `round_down_to_tick` / `round_up_to_tick` / `align_grid_price` /
  `align_tp_price` in `backend/app/trading/deal.py`: every limit price is a
  multiple of `Instrument.tick_size`; grid LONG down / SHORT up (never worse
  than planned), TP LONG up / SHORT down (profit never below the configured
  %). Missing or non-positive `tick_size` → explicit `DealTickSizeInvalid`
  before any order is submitted (no default tick).

### D4. TP ownership and re-arm

- The TP is **one** limit order for the whole current position quantity (from
  `PositionManager`, rounded down to whole lots), priced at
  `average_price × (1 ± tp%)` (LONG `+`, SHORT `−`) from the PositionManager
  **average** — never the market price — then D3-aligned.
- Re-arm on every grid fill: cancel the old TP, await the confirmation (or a
  terminal state), then place the new TP from the current position. If the old
  TP filled during the cancel, the new TP is recomputed from the actual
  position. Never two working TPs.
- Cancel failure / unknown TP state → no second TP, bot new submissions
  blocked, deal marked as needing reconciliation (`DealBlocked`).

### D5. Durable deal state and recovery

- `LiveRecoveryCoordinator`
  (`backend/app/trading/recovery.py`) recovers after the existing
  order/position reconciliation: non-CLOSED Deals are loaded and matched to
  broker facts level-by-level. No blind grid recreation: a still-active grid
  order stays as-is; a broker-filled grid order is applied as a fill (→ TP
  re-arm per D4); a missing TP while OPEN is placed once after successful
  reconciliation. Unknown order state or a position contradiction → the bot
  goes to ERROR with new submissions stopped.

### D6. The live cycle no longer produces exits

- `backend/app/trading/engine.py`: the live per-bot `TradingEngine.process()`
  in OPEN no longer creates exit intents from `StrategyEngine.evaluate()` —
  the TP is Deal-owned. Backtest and generic engines are unchanged.
- `backend/app/strategies/engine.py`: the live `_entry_price` wrapper
  (`entry_price` for the Deal) is a thin hook; it does not change the DCA/Grid,
  ExitEngine or Backtest mathematics.
- Clean-up: the unreachable duplicate in `make_deposit_provider()`
  (`backend/app/trading/live_execution.py`) was removed (behaviour unchanged,
  covered by the existing MVP-6.11 B2 test).

## Architecture decisions / boundaries

- The deal layer is broker-neutral: no `app.brokers.tinvest*` import in
  `app/trading/deal.py` / `deal_manager.py`; only `ExecutionIntent` /
  `InternalOrder` / `Fill` / `OrderState` and the existing DCA-grid math.
- `DCAGridEngine`, `ExitEngine` and Backtest mathematics are unchanged; they
  are reused (verified by the unchanged existing engine suites).
- Everything not covered by D1–D6 stops at the boundary and is documented here:
  Multi-Take / break-even / Signal TP / stop-loss / signal stop / pull-up /
  SIGNAL grid mode are rejected at START (D1) — separate future MVPs; the live
  cycle scheduler is still outside this MVP (the strategy cycle is invoked
  explicitly).
- T-Invest stays read-only in the live runtime: fills are routed through the
  existing broker-neutral `OrderManager` path; no new submission surface is
  enabled (the `RiskManager -> OrderManager -> BrokerAdapter.place_order` path
  is the accepted MVP-6.2 architecture).
- No invented defaults: tick, lot, TP %, deposit, active_limit are all read
  from the persisted instrument/config; a missing tick/lot blocks explicitly.
- The REPORTS/REVIEWS are written to `agent/control` before any publication;
  no self-declared acceptance; no merge into `master`.

## Tests

`backend/tests/test_mvp612_deal_continuation.py` (25 focused tests) maps to
the approved test list (1–13):

1. START rejected (409, named error) for Multi-Take, Signal TP, stop-loss,
   signal stop, pull-up > 0, SIGNAL grid mode; accepted for SIMPLE/CUSTOM +
   Simple TP (`test_d1_accepts_simple_and_custom_fixed_tp`,
   `test_d1_rejects_unsupported_configs`,
   `test_d1_start_rejection_maps_to_409`);
2. Entry from FLAT persists the Deal **before** submission; a sub-lot or tick
   failure on a **non-active** level blocks the whole entry
   (`test_d2_flat_entry_persists_deal_before_submission`,
   `test_d2_below_lot_on_non_active_level_blocks_whole_entry`,
   `test_d2_missing_tick_blocks_whole_entry`,
   `test_d2_no_second_deal_while_one_is_active`);
3. D3: LONG grid rounded down / TP up; SHORT mirrored; missing tick → blocked
   (`test_d3_grid_long_down_short_up`, `test_d3_tp_long_up_short_down`);
4. Entry fill → one TP at `avg × (1+tp%)` for the whole position, lot- and
   tick-rounded; not at the market price (`test_d4_entry_fill_places_tp_from_average_not_market`,
   `test_d4_short_entry_fill_places_tp_mirrored`);
5. DCA partial fill → TP re-armed (old cancelled, new placed) with the new
   average and quantity; exactly one TP working
   (`test_d4_dca_partial_fill_rearms_tp_once`);
6. DCA full fill with `active_limit` → the next waiting level placed; the
   active count stays at `active_limit`
   (`test_d4_dca_full_fill_promotes_next_waiting_level_up_to_active_limit`);
7. TP partial fill → TP kept; TP full fill → remaining grid orders cancelled,
   Deal CLOSED, next FLAT entry uses the current deposit
   (`test_d4_tp_partial_fill_keeps_working_and_full_fill_closes`,
   `test_d2_next_flat_entry_uses_current_deposit`);
8. Old TP fills during re-arm → the new TP is computed from the actual
   position; no double TP (`test_d4_old_tp_fill_during_rearm_computes_from_actual_position`);
9. TP cancel failure / unknown → no second TP, bot blocked with an explicit
   error (`test_d4_tp_cancel_failure_blocks_bot_with_explicit_error`);
10. Recovery: active grid order kept; filled-at-broker order applied and TP
    re-armed; missing TP placed once; unknown order → bot ERROR, no submission
    (`test_d5_recover_keeps_working_orders_and_active_grid`,
    `test_d5_recover_broker_filled_grid_rearms_tp`,
    `test_d5_recover_missing_tp_placed_once`,
    `test_d5_recover_unknown_order_blocks_bot`);
11. D6: OPEN live cycle creates no exit intents from `evaluate()`; Backtest
    suites unchanged (`test_d6_open_live_cycle_creates_no_exit_intents_without_deal`,
    `test_d6_open_deal_keeps_deal_orders_and_places_nothing_new`);
12. `make_deposit_provider()` unchanged in behaviour after the clean-up
    (`test_make_deposit_provider_unreachable_duplicate_removed`);
13. Deterministic intent ids (`test_intent_ids_are_deterministic`).

Existing tests were updated only where the approved contract changed the
behaviour (D6):

- `tests/test_mvp69_position_state.py`: the two engine-level "exit from
  market price" tests were removed (their coverage is replaced by the
  Deal-owned TP tests); the pure `StrategyEngine` exit-plan and all
  position-state gating tests are kept.
- `tests/test_mvp611_deposit_sizing.py`: the six OPEN-cycle exit-only /
  C6-while-open tests were removed and replaced by `test_mvp612` coverage
  (the OPEN live cycle no longer submits exit intents); the FLAT deposit
  tests, B1/B2 regressions and C2/C3 tests are unchanged.
- `tests/test_mvp610_market_snapshot.py::test_position_invariant_valid_snapshot_and_position`:
  the OPEN cycle now places **no** order (0 `place_calls`, no orders) instead
  of one exit — the TP is Deal-owned.

## Commands / results

- `pytest` (backend, full suite): **433 passed, 1 skipped** (the single skip
  is the opt-in live sandbox integration test).
- `ruff check app tests scripts`: **All checks passed!**
- `alembic heads`: single head `0005_deal_continuation` (chain
  `0004_bot_deposit -> 0005_deal_continuation`).
- `npm run build` (frontend): **built successfully** (no frontend changes).

## Constraints honoured

- `DCAGridEngine` mathematics, Veles Filter/Signal semantics, Backtest
  behaviour, `Decimal`/UTC handling and broker neutrality are unchanged
  (verified by the diff review and the unchanged existing suites).
- T-Invest stays read-only in the live runtime: this MVP routes fills through
  the existing broker-neutral path; no production order submission is enabled
  beyond the accepted MVP-6.2 `RiskManager -> OrderManager -> place_order`
  path.
- No invented defaults: tick, lot, TP %, deposit and active_limit all come
  from persisted config/instrument; missing values block explicitly.
- Everything not covered by D1–D6 stops at the boundary and is documented in
  this REPORT (Multi-Take / Signal TP / break-even / SL / signal stop /
  pull-up / SIGNAL mode, live cycle scheduler).
- The REPORT is written to `agent/control` before any publication; no
  self-declared acceptance; no merge into `master`; Issue #7 stays open.

## Review request

Ready for independent ChatGPT review on `agent/review/mvp-6.12`
(`a4f792d39f12f2db7b88ce64ae3ed766e9200660` against base
`59a38974cd27405f40332806fee7dfa8fabc569e`). No merge into `master` has
been performed; publication requires acceptance first.
