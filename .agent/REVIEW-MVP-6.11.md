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

1. **Deposit edits on a running bot.** `PATCH` does not check the bot state, while the engine reads `Bot.deposit` only when the per-bot engine is built. A running bot keeps its old deposit while the DB already shows the new one. Veles: "Editing an active bot applies new settings from the next deal". The project should choose between rejecting the edit (409) while the bot is active and applying it from the next deal. **Owner decision (2026-09-29): apply from the next deal, as in Veles → contract C6, added to correction round 1 (see the task).**
2. **`PATCH {}` clears the deposit.** A missing `deposit` field is treated as `null`. Consider requiring the key explicitly (`model_fields_set`). This can be done in the same correction round if trivial; not blocking.
3. **C3 checks only `plan.grid`** (the currently active levels). With `active_limit`, later levels of the same deal are not checked. They are never submitted in MVP-6.11, but the deal-continuation MVP must re-apply C3 to every level it places.
4. **Position state is per FIGI, not per bot.** Two bots on the same instrument, or a manual trade, share one position. Pre-existing architecture; relevant for multi-bot and "include existing position" features.
5. **TP price is derived from the market-context price**, not from the average entry price (pre-existing, stated in the REPORT). This must be fixed before or together with deal continuation.
6. **The `PROJECT_STATE.md` wording** about T-Invest order submission is fixed on `agent/control` by the reviewer (documentation owner).

## Acceptance conditions (round 2)

1. B1 corrected as described, with the regression tests.
1a. C6 implemented as specified in the task (deposit read at each FLAT entry), with its tests.
2. Full `pytest`, `ruff check app tests scripts`, `npm run build` re-run.
3. New commit on `agent/review/mvp-6.11` **pushed to GitHub**; REPORT rev1 (`.agent/REPORT-MVP-6.11-REV1.md`) committed **and pushed** to `agent/control`, citing the pushed SHA.
4. `master` unchanged.

**No publication to master.**

---

## Round 2 — Verdict

**REJECTED — one correction required (B2).** B1 and C7 are closed. C6 works in the engine but not in the production wiring.

Reviewed: `a6aaba5` (`agent/review/mvp-6.11`, pushed, in sync with origin), base `master @ 10d445e` (merge-base verified).
Report: `.agent/REPORT-MVP-6.11-REV1.md` (`agent/control @ 9b25e25`). Reviewer: Claude, 2026-09-30.

### Independent re-run

| Check | Result |
|---|---|
| `pytest` (full, Python 3.12) | **411 passed, 1 skipped** — matches REV1 |
| `ruff check app tests scripts` | All checks passed |
| `alembic heads` | single head `0004_bot_deposit` |
| frontend | no frontend diff since round 1 (build verified in round 1) |
| push rule | review branch and REPORT pushed; REPORT cites the pushed SHA ✓ |

### Closed

- **B1 — CLOSED.** The round-1 probe re-run on `a6aaba5`: OPEN + `deposit=None` → exit `SELL 10`; OPEN + SIGNAL → exit `SELL 10`. `_entry_base_nominal()` resolves C2 only on FLAT (or for a generic engine). The regression tests from the review are present.
- **C7 — CLOSED.** `get_snapshot()` trims to `candles[-lookback_bars:]`. The test covers `lookback_bars + 1` → exactly `lookback_bars`, with the newest candle last, contiguous and chronological. Existing MVP-6.10 tests are unchanged (additions only). Issue #3 stays open until publication, as required.
- **Observation 2 — closed.** The `deposit` key is required on PATCH (`PATCH {}` → 422, the stored value is unchanged).

### Blocking finding

#### B2. C6 does not work in production: the deposit provider reads a stale cached `Bot`

`build_live_service()` wires `_deposit_provider` → `bot_repository.get(bot_id)` → `AsyncSession.get(Bot, id)` on the **long-lived live-service session** (`SessionLocal()`, created once; `app/core/db.py` sets `expire_on_commit=False`). The same session has already loaded that `Bot` (bot restore, engine factory), so `Session.get()` returns the **identity-map instance without querying the database**. `PATCH /api/bots/{id}` writes through a **different** (per-request) session.

Reproduced with two real `AsyncSession`s (aiosqlite, same `async_sessionmaker(expire_on_commit=False)` config, the project's `BotRepository`):

```
live sees before PATCH: 10000
DB after PATCH:         20000
provider (live) reads:  10000   ← stale; the edit never reaches the next deal
```

The C6 tests pass only because they inject a fake provider; the production provider path is not covered.

**Required correction**

1. The deposit provider must read the **current database value** on every FLAT entry. For example, add a repository method that queries with `populate_existing=True` (`session.get(Bot, bot_id, populate_existing=True)` or `select(Bot).where(Bot.id == bot_id).execution_options(populate_existing=True)`), or read through a short-lived session. Do not change the API session model.
2. A regression test with **two real sessions** (e.g. `aiosqlite` as a dev-only dependency, creating only the tables needed): load the bot in session A (the live session), update the deposit through session B with the existing `BotRepository.update_deposit`, then the production provider/repository method on session A returns the new value.
3. The test must exercise the **same function the production wiring uses** (not a fake provider). If the provider stays a closure inside `build_live_service()`, extract it (e.g. `make_deposit_provider(repo, bot_id)`) so it can be tested directly.
4. `§29` updated with a single sentence on the fresh DB read. REPORT → `.agent/REPORT-MVP-6.11-REV2.md`, pushed, citing the pushed SHA.

### Minor (non-blocking)

- Issue #3 asked for a separate commit `fix: enforce exact market snapshot lookback`; C7 was bundled into `a6aaba5`. This is acceptable because the task (C7) did not require a separate commit.
- Round-1 observations 3–5 remain open for the follow-up MVPs.

**No publication to master.**

---

## Round 3 — Verdict

**ACCEPT**

Accepted implementation: `e026886dfdc` (`agent/review/mvp-6.11`, pushed, in sync with origin), base `master @ 10d445e`.
Report: `.agent/REPORT-MVP-6.11-REV2.md` (`agent/control @ 46285d7`). Reviewer: Claude, 2026-09-30.

### Independent re-run (clean environment, Python 3.12, `pip install -e ".[dev]"`)

| Check | Result |
|---|---|
| `pytest` (full) | **412 passed, 1 skipped** — matches REV2 |
| `ruff check app tests scripts` | All checks passed |
| `aiosqlite` | already declared as a dev-only extra in `pyproject.toml`; resolves on a clean install |
| frontend | no frontend diff in any MVP-6.11 round (build verified in round 1) |

### B2 — CLOSED

- `BotRepository.get_deposit()` reads with `session.get(Bot, id, populate_existing=True)`, a fresh DB read on the long-lived session.
- `make_deposit_provider(bot_repository, bot_id)` is a module-level function, and `build_live_service()` wires exactly it (`deposit_provider=make_deposit_provider(bot_repository, bot_id)`). The remaining `bot_repository.get(bot_id)` calls in the wiring load the bot only to resolve its instrument, not the deposit.
- Regression test with two real `AsyncSession`s over a file-based aiosqlite DB, on the production function: a plain `get` on the live session stays at 10000 (the stale scenario is reproduced) while the provider returns 20000, and `None` after a clearing edit. This matches the review's reproduction.

### MVP-6.11 summary (all rounds)

C1–C5 (round 1), B1 + C6 + C7 (round 2), B2 (round 3) — all closed.

### Follow-ups (non-blocking)

1. `make_deposit_provider()` contains a duplicated, **unreachable** copy of the inner function after `return` (`live_execution.py`, directly below the first `return _deposit_provider`). It is harmless dead code; remove it in the next MVP.
2. Round-1 observations 3–5 remain open: C3 must be applied to every level in deal continuation; position state is per FIGI, not per bot; TP is derived from the market price, not the average entry price.
3. Publication steps: merge `agent/review/mvp-6.11` → `master` via PR (no force, no rebase), then mirror the MVP-6.11 control records to `master` and add the "Mandatory push rule" to `AGENTS.md` §6 on `master`, then close Issues #3 and #5.
