# Veles-MOEX — REPORT: MVP-6.11 REV1 (round-1 correction)

## Correction commits

1. `a6aaba5` — "review: implement MVP-6.11 round-1 correction (B1 + C6 + C7)"
   (correction on `agent/review/mvp-6.11`).

- Round-1 implementation reviewed: `e036c0e74e8ac50f6d4b2bd82842c0a90b845120`.
  Round-1 review: `.agent/REVIEW-MVP-6.11.md` (REJECTED, B1).
- Base before MVP-6.11: `master @ 10d445e0af61c617d7484ca38d79a94cb45b0aa0`.
- Correction HEAD on the review branch: `a6aaba5` (pushed to GitHub, in sync
  with `origin/agent/review/mvp-6.11`).
- No changes to `master`; publication requires independent acceptance
  (round-2 decision).

## What changed (B1 + C6 + C7)

### B1. Entry sizing is an entry-only precondition (round-1 rejection)

- `backend/app/trading/engine.py`: `process()` no longer resolves the C2 base
  nominal eagerly. It calls the new `_entry_base_nominal(position_state)`:
  - FLAT (and a generic engine without a live position state) → C2 is
    resolved as before (`SizingNotConfigured` / `SignalSizingUnsupported` /
    `CustomDepositExceeded` still block **entries** explicitly);
  - OPEN / UNKNOWN / SIGN_MISMATCH → `None`: `evaluate(..., base_nominal=None,
    position_qty=<real qty>)` builds **exits only**; the grid is discarded on
    OPEN anyway.
- Exits of an open deal now depend only on the PositionManager quantity
  (`_exit_position_quantity`), never on the deposit or the grid mode: an open
  position keeps its TP/SL maintenance when the deposit is unset, cleared, or
  the grid mode is SIGNAL / CUSTOM-over-100%.
- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md §29` updated: "Entry
  sizing is an entry-only precondition (B1)".

### C6. Deposit edits apply from the next deal (owner decision, Veles semantics)

- `TradingEngine` accepts an optional async `deposit_provider`
  (`Callable[[], Awaitable[Decimal | None]]`); on the FLAT entry path it is
  called at the moment of the entry and C2 is resolved with the current value.
  A deposit edit applies from the next deal without a bot restart; an open
  deal never reads the provider.
- `build_live_service()` wires a provider reading `Bot.deposit` from the
  repository per entry; the engine no longer snapshots the deposit at build
  time (`PositionSizing(lot_size=…, currency=…)` + `deposit_provider`).
- Review observation 2 also addressed: the `deposit` key is **required** on
  PATCH (`BotDepositUpdate.deposit: Decimal | None = Field(gt=0)`, no
  default) — a PATCH without the key is 422 and cannot silently clear the
  stored value; an explicit `null` still clears.
- `docs §29` updated (C6 section).

### C7. Snapshot trimmed to exactly `lookback_bars` (GitHub Issue #3 carry-over)

- `backend/app/services/market_data.py:get_snapshot()`: after the non-empty
  check the received candles are trimmed to the newest `lookback_bars`
  (`candles = candles[-lookback_bars:]`) — chronological order preserved,
  newest candle retained last. Fewer-than-`lookback_bars` candles are kept
  as-is.
- GitHub Issue #3 is **referenced** in the report and in `docs §29`; the
  issue is **NOT closed** here — per the task contract it is closed only
  after publication to `master`.
- `docs §29` updated (C7 section).

## Regression / new tests

- `backend/tests/test_mvp611_deposit_sizing.py` (37 tests):
  - B1: OPEN + `deposit=None` → exit submitted, no grid; OPEN + SIGNAL mode →
    exit submitted; OPEN + CUSTOM Σ>100% → exit submitted; FLAT +
    `deposit=None` → `SizingNotConfigured`, nothing placed.
  - C6: deposit edit while RUNNING + FLAT → next entry uses the new value
    without a restart; edit while OPEN → exit repeats unchanged (stable
    intent id, no duplicate), next FLAT entry uses the new value; deposit
    cleared while OPEN → exit unaffected, next FLAT entry →
    `SizingNotConfigured`.
  - Schema/API: `BotDepositUpdate()` (missing key) raises `ValidationError`;
    `PATCH {}` → 422 with the stored deposit unchanged.
- `backend/tests/test_mvp610_market_snapshot.py` (26 tests):
  - C7: broker returns `lookback_bars + 1` candles → the snapshot contains
    exactly `lookback_bars`, the newest last, contiguous and chronological.

## Validation (round 2)

| Check | Result |
|---|---|
| `pytest` (backend, full) | **411 passed, 1 skipped** |
| `ruff check app tests scripts` | **All checks passed** |
| `npm run build` (frontend) | **built** (no frontend changes) |

## State

- `agent/review/mvp-6.11` committed and pushed (`a6aaba5`).
- `agent/control` carries this report; `PROJECT_STATE.md` updated (round 2,
  awaiting decision).
- `master` unchanged. Issue #3 open pending publication.

**No self-declaration of acceptance.**
