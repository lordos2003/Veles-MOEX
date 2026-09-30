# Veles-MOEX — REPORT: MVP-6.12 REV1 (round-1 correction)

## Correction commits

1. `949bebe` — "review: implement MVP-6.12 round-1 correction (B1 + B2 + D7)"
   (correction on `agent/review/mvp-6.12`).

- Round-1 implementation reviewed: `a4f792d39f12f2db7b88ce64ae3ed766e9200660`.
  Round-1 review: `.agent/REVIEW-MVP-6.12.md` (REJECTED, B1 + B2, plus owner
  contract D7).
- Base before MVP-6.12: `master @ 59a38974cd27405f40332806fee7dfa8fabc569e`
  (merge-base verified: `git merge-base origin/master agent/review/mvp-6.12`).
- Correction HEAD on the review branch: `949bebe` (pushed to GitHub, in sync
  with `origin/agent/review/mvp-6.12`).
- No changes to `master` (`origin/master` now `0622851`, a docs-only "rename
  OpenCode to Кодер" commit — no implementation changes); publication still
  requires independent acceptance (round-2 decision).

## What changed (B1 + B2 + D7, and review observation 2)

### D7. Reducing intents are exempt from growth limits (owner contract, 2026-09-30)

`backend/app/trading/risk_manager.py`:

- `check_order()` keeps its order of checks: emergency stop → quantity →
  price → instrument permission → `_is_reducing(intent)` → position size →
  daily loss. A reducing intent returns after the four unconditional checks,
  so `max_position_size` and `daily_loss_limit` never block a closing
  order, while emergency stop, quantity, price and instrument permission
  still apply.
- `_is_reducing()` (broker-neutral, no broker import): the intent is reducing
  when the PositionManager position for its FIGI is non-zero, the intent side
  is opposite to the position sign, and `abs(intent.quantity) <=
  abs(position.quantity)`. A same-side intent, an intent exceeding the
  position magnitude, or an unknown position is treated as increasing (no
  exemption) — the old MVP-6.6 behaviour is unchanged for those.
- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`: §10.1 gains the D7
  exemption paragraph (after item 6), §30 intro becomes "D1–D7", and §30
  gains `### D7. Reducing intents are exempt from growth limits (owner
  contract)` plus `### Correction round 1 (independent review, 2026-09-30)`.

### B1. The old TP must stay working until the new one is risk-accepted; no exception escapes the pump

`backend/app/trading/deal_manager.py`:

- `_rearm_tp()` computes the new TP (position, quantity, price from
  PositionManager facts) and runs `RiskManager.check_order()` **first**;
  `RiskRejected` is wrapped into `DealOrderRejected`. Only after the risk
  check passes is the old TP cancelled and the new one placed. A risk
  rejection therefore leaves the old TP in place, and the Deal transitions
  ERROR (B2) — the position is never left without a TP.
- `_submit_level()` wraps `RiskRejected` into `DealOrderRejected` the same
  way (a risk-rejected grid order is a Deal error, never a silent skip).
- `pump()` handles **every** exception per event: the offending event marks
  exactly that Deal ERROR, records the error, blocks the bot (B2) and the
  loop **continues** with the remaining queued events. Nothing is lost and
  nothing escapes the stream's `on_event` hook (a best-effort
  `BotRuntimeManager` notification is also guarded, and a failing store save
  inside `_fail_deal` cannot break the per-event boundary either).
- `_rearm_tp()` increments `deal.tp_rev` before the risk check so the intent
  id stays deterministic per attempt; on rejection the Deal is ERROR and never
  re-arms again, so no TP gap can appear.

### B2. Deal errors surface through the bot lifecycle and the API

- `backend/app/trading/bot_lifecycle.py`: new public `BotRuntime.fail(reason)`
  — transitions RUNNING/STOP_REQUESTED to ERROR (no-op for STOPPED,
  EMERGENCY_STOP, ERROR) and releases the bot from the RiskManager active
  count if it was running.
- `DealManager` gains a broker-neutral `on_bot_error` callback and funnels
  **every** failure path (`pump()`, `open_deal()`, `recover()`) through
  `_fail_deal()`: Deal → ERROR (unless already CLOSED), bot blocked for new
  submissions, reason recorded (`last_error_for(bot_id)`), lifecycle notified.
- `backend/app/trading/live_execution.py`: `build_live_service()` wires
  `_deal_bot_error` after `BotRuntimeManager` creation — it calls
  `runtime.fail(reason)` and persists `BotState.ERROR` through the
  `BotRepository` (the closure late-binds the runtime/repository, so the
  circular wiring is resolved); `LiveExecutionService.deal_manager` is
  exposed.
- `backend/app/api/deps.py` + `backend/app/api/bots.py` +
  `backend/app/bots/schemas.py`: `GET /api/bots/{id}` exposes a read-only
  `deal_error` field (`BotResponse.deal_error: str | None`) backed by
  `deal_manager.last_error_for(bot_id)`; no write path changed.
- `backend/app/trading/engine.py`: in the OPEN branch, after the position is
  reconciled OPEN, `assert_deal_for_open_position()` is called — an OPEN
  position without an owning non-CLOSED Deal notifies the lifecycle and
  raises `DealPositionContradiction` (cycle stops), instead of silently
  building an empty plan. This replaces
  `test_d6_open_live_cycle_creates_no_exit_intents_without_deal` with
  `test_b2_open_live_position_without_deal_errors_the_bot`.
- A new START after ERROR follows the existing lifecycle; a blocked deal must
  be reconciled (D5) before a new Deal opens (unchanged contract).

### Review observation 2 (non-blocking, addressed)

- `test_deposit_edit_during_open_does_not_affect_owning_deal`: deposit
  edited/cleared while a Deal is OPEN → the TP re-arm on the next grid fill is
  unchanged (the Deal owns the captured deposit; the re-arm never reads it).
- Review observation 1 (recovery re-arms the TP on every restart, causing
  cancel/replace churn) is **not** addressed — it was non-blocking, and the
  current D5 recovery logic was left untouched for round 2.

## Tests added / replaced

`backend/tests/test_trading_risk.py` (D7, 7 tests):

- `test_d7_reducing_sell_exempt_from_position_size_limit`
- `test_d7_reducing_buy_exempt_for_short_position`
- `test_d7_quantity_beyond_position_is_not_reducing`
- `test_d7_reducing_exempt_from_daily_loss_limit`
- `test_d7_emergency_stop_still_blocks_reducing`
- `test_d7_blocked_instrument_still_blocks_reducing`
- `test_d7_without_position_manager_no_exemption`

`backend/tests/test_mvp612_deal_continuation.py` (B1/B2/regressions):

- `test_b2_open_live_position_without_deal_errors_the_bot` (replaces the old
  D6 silent-ignore test)
- `test_d7_tp_placed_under_position_size_limit` (review probe P1)
- `test_d7_dca_fill_rearms_tp_under_daily_loss_limit` (review probe P2)
- `test_b1_risk_rejected_rearm_keeps_old_tp_and_fails_deal` (review probe 3:
  a rejection D7 does not exempt, `RearmRejectingRisk` for one bot only —
  old TP stays working, Deal → ERROR, bot blocked)
- `test_b1_pump_isolates_one_failing_deal_in_a_batch` (mixed batch: the
  failing event is isolated, the remaining events are still applied)
- `test_b2_api_surfaces_deal_error` (`GET /api/bots/{id}` shows `deal_error`)
- `test_b2_runtime_fail_moves_bot_to_error` (lifecycle ERROR + persistence)
- `test_deposit_edit_during_open_does_not_affect_owning_deal` (observation 2)

## Validation

| Check | Result |
|---|---|
| `pytest` (full, backend) | **447 passed, 1 skipped**, 2 warnings (pre-existing Starlette/httpx deprecations) |
| `ruff check app tests scripts` | All checks passed |
| `alembic heads` | single head `0005_deal_continuation` (no model/migration change in this correction) |
| `npm run build` (frontend) | built successfully (no frontend changes in this correction) |

## Known limitations

- Deal-level knowledge is in-memory until a restart; after a restart the
  persisted Deal and the reconciled broker facts drive recovery (D5) — an
  unreconcilable Deal puts the bot in ERROR with the reason observable via
  `deal_error` (no silent continuation).
- The D7 exemption applies only when the current position is known through
  the PositionManager; without it the order is treated as increasing.
- On a deal error the bot enters ERROR and stays blocked until an explicit
  START; the deal itself needs an explicit reconciliation (D5) before a new
  Deal is opened — same as the accepted round-1 behaviour, now surfaced.

## Acceptance mapping (round 2)

1. D7 implemented in `RiskManager` with tests (reducing vs increasing, both
   limits, emergency stop still blocking) — done.
2. B1 and B2 corrected as described, with the listed regressions — done.
3. Full `pytest`, `ruff`, `alembic heads`, `npm run build` — done (above).
4. Commit pushed to `agent/review/mvp-6.12`; `.agent/REPORT-MVP-6.12-REV1.md`
   committed and pushed to `agent/control`, citing the pushed SHA — this
   report does that (`949bebe`, in sync with origin).
5. `master` unchanged — no changes to `master` from this work.

**No publication to master.**
