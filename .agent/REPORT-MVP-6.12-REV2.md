# Veles-MOEX — REPORT: MVP-6.12 REV2 (round-2 correction)

## Correction commits

1. `418c24e` — "review: implement MVP-6.12 round-2 correction (B3)"
   (correction on `agent/review/mvp-6.12`).

- Round-2 implementation reviewed: `949bebe` (B1 + B2 + D7, round-1
  correction). Round-2 review: `.agent/REVIEW-MVP-6.12.md` (REJECTED, B3
  only; D7/B1/B2 closed).
- Base before MVP-6.12: `master @ 59a38974cd27405f40332806fee7dfa8fabc569e`.
- Correction HEAD on the review branch: `418c24e` (pushed to GitHub, in
  sync with `origin/agent/review/mvp-6.12` — verified by
  `git ls-remote`).
- No changes to `master` (`origin/master` `0622851`, unchanged);
  publication still requires independent acceptance (round-3 decision).

## What changed (B3)

### B3. A fill is a broker fact: fills during (and after) a TP cancel are applied, and the new TP never exceeds the actual position

`backend/app/trading/domain.py`:

- `ALLOWED_TRANSITIONS[OrderState.CANCEL_REQUESTED]` now also allows
  `PARTIALLY_FILLED` and `FILLED` (the cancel in flight can lose the race
  to an exchange fill). The terminal `CANCELLED` state itself still accepts
  no status change (comment documents the rule).

`backend/app/trading/order_manager.py`:

- `apply_fill()`: a fill is a broker fact and is never dropped. On a fill
  the order is transitioned to `PARTIALLY_FILLED`/`FILLED` only when it is
  not already terminal; an order in a terminal state (e.g. `CANCELLED` after
  an exchange race fill, `FILLED` after a late duplicate) **keeps its
  state**, but the fill still updates the recorded quantity/price and the
  `PositionManager` position below. No exception on
  `CANCEL_REQUESTED -> PARTIALLY_FILLED` any more.
- `cancel()`: after the broker confirms the cancel, only a still-live order
  is transitioned to `CANCELLED`; a terminal outcome (the order filled while
  the cancel was in flight) wins and is kept.

`backend/app/trading/deal_manager.py`:

- `_rearm_tp()`: after the cancel returns (confirmed), the position is
  **re-read** (B3). If the position is gone (zero) or empty, the Deal is
  closed (`_close_deal`) and no new TP is placed; a sign contradiction is a
  `DealPositionContradiction` (B2). Otherwise the new TP quantity/price are
  rebuilt from the **actual** post-cancel position facts (lot-rounded down,
  tick-aligned LONG up / SHORT down). When the fresh facts differ from the
  pre-cancel build, a new intent is built (next `tp_rev`) and
  `check_order()` is re-run — so the new TP can never exceed the actual
  position, and zero → close. The intent construction is factored into a
  `_tp_intent(deal, quantity, price)` helper (increments `tp_rev`, builds
  the deterministic intent id, wraps `RiskRejected` → `DealOrderRejected`),
  so both the pre-cancel and post-cancel builds are identical.
- `recover()`: a Deal that `_recover_one` closes during recovery (position
  zero / TP fully filled while its cancel was in flight) is **not
  re-registered** as active — previously the closed Deal was pushed back
  into `self._deals`, which would block the next entry and make
  `active_deal()` non-None. Now the success path skips CLOSED Deals.

`backend/tests/test_mvp612_deal_continuation.py` (3 new tests; `FakeBroker`
gains an `on_cancel(hook)` hook invoked inside `cancel_order` after the
cancel is recorded, to simulate the exchange race):

- `test_b3_partial_old_tp_fill_during_cancel_rebuilds_from_actual_position`:
  the old TP (200 @ 110) is filled 100 during the cancel after a DCA fill
  (50 @ 99, position 250 → 150). Asserts exactly one working TP for the
  remaining 150 @ 109.8 (from the actual average), `tp_rev == 2`, the old
  TP is `CANCELLED` with `filled_quantity == 100`, and a second
  `pump()` does not place another TP.
- `test_b3_full_old_tp_fill_during_cancel_closes_deal`: the old TP is fully
  filled during the cancel (recovery re-arm path). Asserts the Deal is
  `CLOSED`, the TP `FILLED`, no new TP, `recover()` returns True and no
  active Deal remains (a closed Deal is not re-registered).
- `test_b3_fill_after_cancel_still_updates_position`: a fill for an order
  already `CANCELLED` is applied to the position and recorded while the
  terminal state is kept — no exception, the Deal stays OPEN.

`docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`:

- §30 gains `### Correction round 2 (independent review, 2026-09-30)` —
  the B3 transition rule, the `cancel()` terminal-keep, the `_rearm_tp()`
  post-cancel re-read/rebuild (never exceed the position; zero → close),
  and the recovery no-re-register rule.

## Validation (backend venv, Windows Git Bash)

| Check | Result |
|---|---|
| `pytest` (full, `backend/`) | **450 passed, 1 skipped** (447 → 450: the 3 B3 tests) |
| `ruff check app tests scripts` | All checks passed |
| `alembic heads` | single head `0005_deal_continuation` |
| `npm run build` | green (frontend unchanged) |

The previously failing probes (fill during cancel → `OrderStateError`,
new TP sized 400 @ 109.5 from the pre-cancel position) are covered by the
B3 tests: a fill during the cancel applies, and the new TP is rebuilt from
the actual post-cancel position (150 @ 109.8 in the partial case), never
larger than it. D1–D7, B1, B2 and the observation-2 regression all still
pass; the rev-count tests
(`test_d4_dca_partial_fill_rearms_tp_once` rev == 2,
`test_d4_old_tp_fill_during_rearm_computes_from_actual_position` rev == 3)
verify the rebuild happens only when post-cancel facts differ, so a
well-behaved cancel still re-arms exactly once per grid fill.

## Non-blocking observations from round 2 — status

1. "Order already filled" from the broker → `UNKNOWN` → Deal ERROR — **not
   addressed** (safe but noisy; a terminal `FILLED` after a refresh would
   be a follow-up).
2. TP re-armed on every restart (round-1 observation 1) — **still open**.
3. FLAT entry failure (`SizingBelowLot`) now puts the bot in ERROR instead
   of blocking one cycle (B2/C3 behavioural change, noted acceptable by the
   reviewer) — **kept as is**.

## Known limitations / documentation gaps

- The exchange-race fill is modelled in tests through the `FakeBroker`
  cancel hook; the real T-Invest adapter path (a fill event and a cancel
  acknowledgement over the stream) is exercised by the same state/common
  code, but no live-market verification was performed.
- No new Veles-derived semantics were introduced; B3 is an order-state /
  position-accounting correction to the already-approved D1–D7 contracts.
