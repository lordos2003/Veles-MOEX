# Veles-MOEX — Independent Review: MVP-6.11

## Verdict (round 1)

**REJECTED — one correction required before acceptance**

Reviewed implementation: `e036c0e74e8ac50f6d4b2bd82842c0a90b845120` (`agent/review/mvp-6.11`)
Base: `master @ 10d445e0af61c617d7484ca38d79a94cb45b0aa0` (merge-base verified)
Report: `.agent/REPORT-MVP-6.11.md` (`agent/control @ 3f5bf70`)
Reviewer: Claude (independent review), 2026-09-29

## Independent re-run

Executed on a clean worktree of `e036c0e` with Python 3.12:

| Check | Result |
|---|---|
| `pytest` (backend, full) | **403 passed, 1 skipped** — matches the REPORT |
| `ruff check app tests scripts` | **All checks passed** |
| `alembic heads` / `history` | single head `0004_bot_deposit`; chain `0001 → 0002 → 0003 → 0004` |
| `npm ci && npm run build` | **built** (no frontend changes) |
| diff vs merge-base | 18 files, +1267/−53, read in full for the trading layer |
| control branch | `678c433..3f5bf70` adds only `REPORT-MVP-6.11.md`; the task and `PROJECT_STATE.md` are intact |

## Blocking finding

### B1. Exits of an OPEN position depend on entry sizing

`TradingEngine.process()` resolves the entry sizing **before** the live position state is known:

```python
base_nominal = self._sizing.resolve_base_nominal(self._strategy_config.dca_grid)   # engine.py:162
...
position_state = self._live_position_state()
```

Any sizing error therefore aborts the whole cycle, including the OPEN path, where only exits are allowed and no entry sizing is needed.

Reproduced with a probe built on the MVP-6.11 test helpers (OPEN position of 10 units, reconciled, TP 10%):

| Case | Result |
|---|---|
| `PositionSizing(deposit=None, …)` | `SizingNotConfigured`, **0 orders** (no TP) |
| `DCAGridConfig(mode=SIGNAL)`, deposit 10 000 | `SignalSizingUnsupported`, **0 orders** (no TP) |

Consequences:

- `PATCH /api/bots/{id}` with `deposit: null` (allowed at any time) on a bot with an open deal stops all exit maintenance for that position.
- A SIGNAL-mode bot with an open position (e.g. restored after restart) can never produce an exit. SIGNAL sizing was blocked on purpose for **entries** (C2), not for exits.
- The same applies to `CustomDepositExceeded`.

This contradicts C4: *OPEN → existing MVP-6.9 behaviour (exits with real quantity)*. Exits must depend only on the PositionManager quantity, never on the deposit or the grid mode.

**Required correction**

1. Resolve `base_nominal` (C2) **only on the FLAT entry path**. For OPEN, call `evaluate(..., base_nominal=None, position_qty=<real qty>)`; the grid is discarded on OPEN anyway.
2. Keep the existing behaviour for FLAT: a sizing error blocks the entry explicitly.
3. Regression tests:
   - OPEN + `deposit=None` → exit submitted, no grid;
   - OPEN + SIGNAL mode → exit submitted, no grid;
   - OPEN + CUSTOM with `Σ nominal_percent > 100` → exit submitted;
   - FLAT + `deposit=None` → `SizingNotConfigured`, no orders (unchanged).
4. Update `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md §29`: sizing is an entry-only precondition.

## Accepted in round 1 (no change requested)

- **C1/C5**: `Bot.deposit` is a bot-level `Numeric(20,8)` field, migration `0004`, API validation `> 0`, wiring `Bot.deposit`/`Instrument.lot_size`/`Instrument.currency` → `PositionSizing` → per-bot `TradingEngine` with `bot_id`. No defaults are invented.
- **C2**: `deposit_to_base_nominal()` — SIMPLE `D/Σkⁱ`, CUSTOM `D×pct/100` with the `>100%` guard. **SIGNAL blocked with justification**: the SIGNAL engine does not use `levels` as an order limit. This follows the task's "do not invent a limit" branch. The test values (2747.25 / 3296.70 / 3956.04, Σ = D) were verified independently.
- **C3**: rounded down to whole lots; a level below one lot blocks the whole entry and the error names the level, nominal, price and lot size. A missing lot size or currency blocks the entry.
- **C4**: `LivePositionState` is correct. `load_snapshot → load_state` resets the reconciled flag at the start of **every** `recover()`, so every recovery failure path (orders or positions) leaves the state UNKNOWN. `mark_reconciled()` is set only after stale positions are dropped and broker facts are applied. The coordinator, the OrderManager and the engines share one PositionManager instance. FLAT entry is blocked while the bot has non-terminal orders and when `bot_id` is missing.
- Scope: DCA/Grid math, Filter/Signal semantics, Backtest, `place_order`/transport unchanged. `GridOrder.nominal` is a data carrier only.

## Observations (non-blocking; for the owner / follow-up MVPs)

1. **Deposit edits on a running bot.** `PATCH` does not check the bot state, while the engine reads `Bot.deposit` only when the per-bot engine is built. A running bot keeps its old deposit while the DB already shows the new one. Veles: "Editing an active bot applies new settings from the next deal". The project should choose between rejecting the edit (409) while the bot is active and applying it from the next deal. **Owner decision required; not part of this correction.**
2. **`PATCH {}` clears the deposit.** A missing `deposit` field is treated as `null`. Consider requiring the key explicitly (`model_fields_set`). This can be done in the same correction round if trivial; not blocking.
3. **C3 checks only `plan.grid`** (the currently active levels). With `active_limit`, later levels of the same deal are not checked. They are never submitted in MVP-6.11, but the deal-continuation MVP must re-apply C3 to every level it places.
4. **Position state is per FIGI, not per bot.** Two bots on the same instrument, or a manual trade, share one position. Pre-existing architecture; relevant for multi-bot and "include existing position" features.
5. **TP price is derived from the market-context price**, not from the average entry price (pre-existing, stated in the REPORT). This must be fixed before or together with deal continuation.
6. **The `PROJECT_STATE.md` wording** about T-Invest order submission is fixed on `agent/control` by the reviewer (documentation owner).

## Acceptance conditions (round 2)

1. B1 corrected as described, with the regression tests.
2. Full `pytest`, `ruff check app tests scripts`, `npm run build` re-run.
3. New commit on `agent/review/mvp-6.11` **pushed to GitHub**; REPORT rev1 (`.agent/REPORT-MVP-6.11-REV1.md`) committed **and pushed** to `agent/control`, citing the pushed SHA.
4. `master` unchanged.

**No publication to master.**
