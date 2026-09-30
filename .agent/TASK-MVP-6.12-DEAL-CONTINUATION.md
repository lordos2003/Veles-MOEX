# TASK-MVP-6.12 — Live Deal Continuation (Simple TP, Simple/Custom grid)

## Status

**IN REVIEW — round 1 REJECTED (B1, B2); correction round 1 (+ D7) assigned to Кодер**

Control branch: `agent/control`
Implementation branch: `agent/review/mvp-6.12` (create from current `master` @ `59a3897`)
Base: `master` @ `59a38974cd27405f40332806fee7dfa8fabc569e` (contains accepted MVP-6.11, merge `40cf6ce`)
Date: 2026-09-30

## Why this MVP

After MVP-6.11 the live path can **open** a deal from a confirmed FLAT, but it cannot **conduct** one:

1. **The TP is wrong.** While OPEN, exits come from `StrategyEngine.evaluate()`. It builds exits only when the **entry signal fires in that cycle**, and it uses `entry_price = context.price`, the **current market price** (`backend/app/strategies/engine.py`, `_entry_price`). Veles defines the TP from the **average price of the deal**.
2. **No reaction to averaging.** After a DCA fill nothing recalculates the TP. With a partial grid (`active_limit`), nothing places the next levels.
3. **Grid limit prices are not tick-aligned.** `TInvestAdapter.place_order()` rejects a limit price that is not a multiple of `Instrument.tick_size` (`backend/app/brokers/tinvest.py`, ~line 422). The raw grid prices from MVP-6.11 would be rejected in live trading.
4. **No durable deal state.** After a restart there is nothing to reconcile the grid and TP against (spec §12).

The Backtest engine already conducts a deal (`backend/app/backtest/engine.py`: `_after_entry`, `_place_limit_exits`, `_rearm_exits`, `_init_grid`, `_place_dca_orders`, the DCA-fill branch of the bar loop). MVP-6.12 brings the same deal semantics to Live, event-driven by broker fills. It reuses the existing engines (`DCAGridEngine.on_fill`/`active_orders`, `ExitEngine.build_remaining_take_plans`/`build_exit_orders`) and does not change their mathematics.

## Veles sources (documented behaviour)

Veles Help Center, «Тейк-профит» (https://help.veles.finance/ru/platform/settings/take-profit/), and the project's `Veles TP — research and requirements.md`:

- «Профит» — the profit percentage **from the average price of the deal**; the bot places a **limit** order.
- «При каждом усреднении бот удаляет старый ордер и создаёт новый, с обновлённой ценой и объёмом.»

Veles Help Center, «Режим торговли» (https://help.veles.finance/ru/platform/settings/trading-mode/):

- Simple and Own modes: averaging orders are placed **at entry, all at once**.
- Partial grid placement: «Ограничение числа активных ордеров (например, 3 из 10). Остальные бот добавит позже, по мере исполнения.»

## Approved contracts (project owner, 2026-09-30)

Do not generalise or extend them. Anything not covered → stop at the boundary, document it in the REPORT, ask.

### D1. Supported live configuration (scope)

MVP-6.12 supports live deals only for:

- `DCAGridConfig.mode` ∈ {`SIMPLE`, `CUSTOM`};
- `ExitConfig.take_profit.kind == "fixed_percentage"` (Simple TP);
- `ExitConfig.stop_loss is None` and `ExitConfig.signal_stop is None`;
- `DCAGridConfig.pull_up_percent == 0` (pull-up is not supported yet).

Any other configuration (Multi-Take, Signal TP, break-even, stop-loss, signal stop, pull-up, SIGNAL grid mode) must be **rejected at bot START** with an explicit, named error (HTTP 409 via the existing START error mapping). The bot must never run live with an exit or grid mode that is not conducted. These modes are separate future MVPs.

### D2. Deal lifecycle (event-driven by fills)

A **Deal** is one position cycle of one bot, from the FLAT entry to the closing TP fill.

1. **Open** (FLAT, the existing MVP-6.11 C4 entry path): build the full grid once from the snapshot price with the deposit read at entry (C6), apply C3 and D3 to **every level of the deal**, not only the active ones. If any level fails C3/D3, the whole entry is blocked. Persist the Deal (D5) **before** submitting its orders. Submit the first order plus the active limit levels (all levels, or `active_limit` of them).
2. **Entry fill** (first order filled, fully or partially): place the TP (D4).
3. **DCA fill** (any fill of a grid level, partial or full): `DCAGridEngine.on_fill` / update the level state; re-arm the TP per D4 (cancel the old TP, then place a new one); for a partial grid, place the next waiting level(s) so the number of active levels stays at `active_limit` (Veles: «добавит позже, по мере исполнения»).
4. **TP fill**: a partial TP fill keeps the TP order working (no re-arm). When the position reaches zero, cancel all remaining working grid orders of the deal. Once the cancellations are confirmed, the Deal is `CLOSED` and the bot returns to the MVP-6.11 FLAT entry path (next deal, fresh deposit per C6).
5. The deposit used by every order of a Deal is the one **captured at the Deal's entry**, stored on the Deal (MVP-6.11 C6 note). Later deposit edits affect only the next Deal.

Fills are routed through the existing broker-neutral path (`OrderManager.on_trade_fill` / `apply_fill` → `PositionManager`) and correlated to the Deal by `bot_id` and the deal/level identity carried in the intent id. No broker types may leak into the deal layer.

### D3. Tick rounding (project contract, not a Veles rule)

Every limit price must be a multiple of `Instrument.tick_size`. Round in the **safe direction**:

- **grid (averaging) orders**: never worse than planned: LONG buy price rounded **down**, SHORT sell price rounded **up**;
- **TP**: profit never below the configured %: LONG sell price rounded **up**, SHORT buy price rounded **down**.

Missing/non-positive `tick_size` → block with an explicit error (no default tick). Use `Decimal` only.

### D4. TP re-arm on every fill (project contract; Veles documents re-arm "on each averaging")

- The TP is a single **limit** order for the **whole current position quantity** (from `PositionManager`, rounded down to whole lots), priced at `average_price × (1 ± tp%)` (LONG `+`, SHORT `−`), where `average_price` is the **PositionManager average price of the position** (never the market price). Then D3.
- Re-arm on **every** fill of a grid order, partial or full: cancel the current TP, wait for the cancel confirmation (or a terminal state), then place the new TP. If the old TP filled (fully or partly) during the cancel, recompute from the actual position before placing a new one; never leave two TP orders working.
- If the cancel fails or its result is unknown, do not place a second TP: block the bot's new submissions, mark the deal as needing reconciliation, and surface an explicit error.

### D5. Durable deal state and recovery (spec §12)

- New persisted entity `Deal` (+ Alembic `0005`): `id`, `bot_id`, `instrument_figi`, `direction`, `status` (`OPENING` / `OPEN` / `CLOSING` / `CLOSED` / `ERROR`), `deposit` (captured), `base_nominal`, `reference_price`, planned levels (index, price, quantity, status), the broker/internal order ids of the working grid orders and TP, timestamps. `Decimal` + UTC.
- Recovery (`LiveRecoveryCoordinator`, after the existing order/position reconciliation): load non-CLOSED deals and match their orders to broker facts. **Do not blindly recreate the grid.**
  - A working grid order that is still active at the broker stays in place.
  - A grid order the broker reports filled is applied as a fill, which re-arms the TP per D4.
  - A missing TP while the position is OPEN may be placed once per D4, and only after reconciliation succeeded.
  - Any order in an unknown state, or a Deal that contradicts the broker position, puts the bot into **ERROR** with new submissions stopped (spec §12).

### D6. The live cycle no longer produces exits

For live per-bot engines, `TradingEngine.process()` in the OPEN state must **not** create exit intents from `StrategyEngine.evaluate()` any more: the TP is owned by the Deal (D2/D4). Remove or disable that path for live engines only. Backtest and generic engines are unchanged. Remove the MVP-6.10/6.11 "exits from market price" behaviour and its tests, which the new Deal tests replace.

## Scope

1. D1 START validation.
2. Deal model, repository, migration `0005`, deal manager (broker-neutral, under `app/trading/`), wired into `build_live_service()` and the fill-routing path.
3. D2 lifecycle, D3 rounding, D4 TP re-arm, D5 recovery, D6 cycle change.
4. Clean-up follow-up from MVP-6.11: remove the unreachable duplicate in `make_deposit_provider()` (`backend/app/trading/live_execution.py`).
5. Docs: `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md §30 MVP-6.12` recording D1–D6, sources and boundaries.

## Tests (focused, `backend/tests/test_mvp612_deal_continuation.py`)

1. START rejected (409, named error) for Multi-Take, Signal TP, stop-loss, signal stop, pull-up > 0, SIGNAL grid mode; accepted for SIMPLE/CUSTOM + Simple TP.
2. Entry from FLAT persists the Deal **before** submission; the full grid is checked by C3 + D3 (a sub-lot or tick failure on a **non-active** level blocks the entry).
3. D3: LONG grid prices rounded down and TP rounded up; SHORT mirrored; missing tick size → blocked.
4. Entry fill → one TP at `avg × (1+tp%)` for the whole position, lot- and tick-rounded; **not** at the market price.
5. DCA partial fill → TP re-armed (old cancelled, new placed) with the new average and quantity; exactly one TP working.
6. DCA full fill with `active_limit` → the next waiting level placed; the active count stays at `active_limit`.
7. TP partial fill → TP kept; TP full fill → remaining grid orders cancelled, Deal CLOSED, next FLAT entry uses the current deposit.
8. Old TP fills during re-arm → the new TP is computed from the actual position; no double TP.
9. TP cancel failure / unknown → no second TP, bot blocked with an explicit error.
10. Recovery: active grid order kept; filled-at-broker order applied and TP re-armed; missing TP placed once; unknown order → bot ERROR, no submission.
11. D6: OPEN live cycle creates no exit intents from `evaluate()`; Backtest suites unchanged.
12. `make_deposit_provider()` unchanged in behaviour after the clean-up (existing B2 test green).
13. Full suite green.

## Explicit constraints (AGENTS.md)

- Do not change the mathematics of `DCAGridEngine`, `ExitEngine` or the Backtest engine. Reuse them.
- Broker neutrality: no `app.brokers.tinvest*` imports in the strategy / deal / trading layers.
- `Decimal` for prices, quantities and money; UTC timestamps.
- Every order goes through `RiskManager.check_order()` → `OrderManager`.
- The MVP-6.9/6.11 position-state gates (UNKNOWN / SIGN_MISMATCH → nothing) remain mandatory.
- No invented defaults (tick, lot, TP %, levels). No Veles semantics beyond D1–D6.

## Known boundaries to record (do not implement)

- Multi-Take, break-even, Signal TP / Minimum P&L, stop-loss, signal stop, trailing, pull-up, SIGNAL mode: separate MVPs.
- Live cycle scheduler: separate MVP. Fills arrive through the existing OrderStateStream path, and the entry is still triggered via `execute_strategy`.
- Position state per FIGI (not per bot) stays as is. Two bots on one instrument are not supported. Record this in the REPORT.

## Validation & REPORT

Full `pytest`, `ruff check app tests scripts`, `alembic heads` (single head `0005_*`), `npm run build`, actual diff review against the merge-base.

REPORT → `agent/control:.agent/REPORT-MVP-6.12.md` with: task, branch, **pushed** commit SHA ("pushed, in sync with origin"), exact changes, validation results, known limitations, documentation/specification gaps, AGENTS.md compliance.

Do not publish to `master`. Do not self-declare acceptance.

## Correction round 1 (review 2026-09-30)

Review: `.agent/REVIEW-MVP-6.12.md` — **REJECTED**:
- **B1**: the TP re-arm cancels the old TP before the new one passes the Risk Manager, and non-`DealError` failures escape `pump()`. Reproduced: the position is left without a TP.
- **B2**: deal errors are not surfaced (the bot stays RUNNING); an OPEN position without an owning Deal is silently ignored.

Fix exactly as described in the review. REPORT → `.agent/REPORT-MVP-6.12-REV1.md`.

### D7. Position-reducing orders and the Risk Manager (owner decision, 2026-09-30)

- An intent is **reducing** when the PositionManager position for its FIGI is non-zero, the intent side is opposite to the position sign, and `quantity ≤ |position|`.
- Reducing intents are **exempt** from `max_position_size` and `daily_loss_limit`. A closing TP must never be blocked by a limit meant to stop risk from growing.
- Reducing intents still go through `emergency_stop` (emergency stop blocks everything; the position is left for manual control, MVP-6.5 semantics), quantity, price and instrument-permission checks.
- Non-reducing intents keep the existing MVP-6.6 behaviour unchanged.
- Document D7 in `§30` and in `§10.1` (Risk Manager preconditions) of `TASK-09-LIVE-TRADING-MVP-6.md`.

## Publication (mandatory, see `AGENTS.md` §6 and `.agent/CODER-WORKFLOW.md` → "Mandatory push rule")

```
git push origin agent/review/mvp-6.12
git push origin agent/control
git ls-remote origin agent/review/mvp-6.12 agent/control
```

No `--force`, no rebase. If rejected: `git fetch origin`, `git merge origin/<branch>`, push again. Never push `master`.
