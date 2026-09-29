# TASK-MVP-6.11 — Bot Deposit Sizing & Entry from Confirmed Flat

## Status

**OPEN — assigned to OpenCode**

Control branch: `agent/control`
Implementation branch: `agent/review/mvp-6.11` (create from current `master` @ `10d445e`)
Base: `master` @ `10d445e0af61c617d7484ca38d79a94cb45b0aa0`
Date: 2026-09-29

## Why this MVP

After MVP-6.10 the live path still cannot produce a single order. There are two independent blockers:

1. **No sizing source.** `TradingEngine.process()` always raises `SizingNotConfigured`: there is no authoritative `base_nominal` for a bot (`backend/app/trading/sizing.py`, `backend/app/trading/engine.py:138`).
2. **A flat bot can never enter.** The MVP-6.9 gate (`TradingEngine._exit_position_quantity()` → `_position_gates_execution()`) maps *no position* and *zero quantity* to `None` and blocks **all** live intents, including the very first entry. A bot that starts with no position therefore never opens a deal.

MVP-6.11 closes both blockers with explicitly approved contracts. Everything else stays as accepted.

## Approved contracts (project owner decision, 2026-09-29)

These contracts were explicitly approved by the project owner. They are the only new semantics this MVP may introduce. Do not generalise or extend them.

### C1. Bot deposit — Veles source

Veles Help Center, "Full list of bot settings" (https://help.veles.finance/en/platform/settings/full/):

- Deposit: "The amount within which the bot trades."
- "Spot: the deposit is divided to orders and placed on the exchange."
- "Futures: the deposit is multiplied by leverage, then divided to orders."

Veles Help Center, "Trading mode" (https://help.veles.finance/en/platform/settings/trading-mode/):

- Simple: "Grid of orders: the number of averaging orders to divide the deal volume between them." / "% Martingale: makes each next order larger than the previous one."
- Own/Custom: "you manually set the indent and volume for each order", "Volume = 100%" = single order.

Veles Help Center, DCA/Martingale (https://help.veles.finance/ru/getting-started/strategies/dca/):

- "Новый объём = Объём предыдущего × (1 + % Мартингейла)".
- The SOL/USDT example (3 orders; without martingale ≈3 320 USDT nominal each; with 20% martingale 2 739 / 3 296 / 3 944 USDT, ratio ≈1.2) is consistent with the whole deal volume being divided across the grid orders.

### C2. Deposit → order nominals (approved project contract)

The sum of the nominals of **all** grid orders of one deal (first order included) equals the bot deposit `D`.

- **SIMPLE**: `n = DCAGridConfig.levels` (grid order count, first order included — verify against `GridPriceDistribution.simple_prices()` that `len(prices) == levels`), `k = 1 + martingale_percent/100` (`k = 1` when martingale is off).
  `first_nominal = D / Σ_{i=0}^{n-1} k^i`; level `i` nominal = `first_nominal × k^i` (unchanged `DCAGridEngine` math, only `base_nominal` is now derived).
- **CUSTOM**: level nominal = `D × nominal_percent / 100` (existing `_build_custom` math with `base_nominal = D`). If `Σ nominal_percent > 100`, block with an explicit error (the deal would exceed the deposit).
- **SIGNAL**: same first-order formula as SIMPLE, with `n` = the maximum number of orders of the deal **only if** the existing SIGNAL engine (`_build_signal` / subsequent-order logic in `dca_grid.py`) already uses `DCAGridConfig.levels` as that limit. If it does not, **do not invent a limit**: SIGNAL sizing blocks with an explicit error and the gap is recorded in the REPORT.
- **Leverage / margin are not supported in MVP-6.11.** Deposit is used 1:1 (spot semantics). No leverage field exists in the current config; do not add one.
- **Reinvest** is out of scope.

The conversion `D → base_nominal` must live in one broker-neutral function (e.g. in `app/trading/sizing.py`) with the mode-specific rule above. `DCAGridEngine` mathematics must not be changed.

### C3. MOEX lot rounding (approved project contract, not a Veles rule)

Veles does not define lot rounding (crypto). For MOEX/T-Invest:

- order quantity in units = `nominal / order_price`, then **rounded down** to a whole number of lots (`lot_size` from the instrument);
- if **any** order of the deal rounds to `0` lots, the **whole entry is blocked** for this cycle with an explicit error (e.g. `SizingBelowLot`) that names the level, its nominal, price and lot size; no partial grid is submitted;
- the unused remainder of the deposit after rounding stays unused (no redistribution);
- missing/non-positive `lot_size` or a missing instrument → block with explicit error, no default lot.

The deposit currency is the instrument's trading/price currency. No FX conversion. If the instrument currency cannot be resolved, block.

### C4. Confirmed-flat entry (approved amendment of the MVP-6.9 gate)

The PositionManager stays the only authoritative quantity source. Its state for a bot instrument becomes explicitly three-valued:

| State | Meaning | Allowed live intents |
|---|---|---|
| `UNKNOWN` | never reconciled, reconciliation failed, or position stale | **none** (MVP-6.9 behaviour preserved) |
| `FLAT` | the latest successful broker reconciliation confirmed zero/no position | **entry only** (grid built from the current snapshot) — no exit intents |
| `OPEN` | reconciled non-zero position with a sign matching the strategy direction | existing MVP-6.9 behaviour (exits with real quantity) |
| sign mismatch | reconciled position with the opposite sign | **none** |

Rules:

- `FLAT` must come only from a successful reconciliation through `BrokerAdapter.get_open_positions()` (existing `LiveRecoveryCoordinator` path). "Absent from the dict" is **not** `FLAT` unless the reconciliation that produced the state succeeded.
- Entry from `FLAT` is allowed only if the bot has **no active (non-terminal) orders** in `OrderManager`. Otherwise block entry for this cycle (prevents re-entering on every cycle while a limit first order or grid is still working).
- While `OPEN`, the live cycle must **not** submit new grid/entry intents from a fresh `evaluate()` (deal continuation / grid state persistence across cycles is out of scope and must be recorded as a known boundary). Exit intents keep the MVP-6.9 behaviour.
- `resolve_quantity()` semantics for exits stay as accepted (positive magnitude or domain error).

### C5. Where the deposit lives

The deposit is a **bot** setting (Veles: bot settings), not a strategy setting.

- Add `Bot.deposit` (`Numeric`, nullable) + Alembic migration `0004`.
- `Decimal` everywhere; `None` or `<= 0` → `SizingNotConfigured` (existing behaviour, unchanged meaning).
- Wire `Bot.deposit` → `PositionSizing` → per-bot `TradingEngine` in `build_live_service()` / `BotRuntime`. No global/implicit/default deposit.
- Expose `deposit` in the existing bot API schema (read/write) with validation `> 0`. Frontend change only if needed for the existing bot form to keep building; no UI redesign.

## Scope

1. Broker-neutral sizing: `D → base_nominal` per mode (C2), lot rounding (C3), explicit errors.
2. `Bot.deposit` persistence, migration, API schema, live wiring (C5).
3. PositionManager three-state position (C4) fed by the existing reconciliation; `TradingEngine.process()` gating updated exactly per the C4 table.
4. Entry path: from `FLAT` with no active bot orders, the grid built by `StrategyEngine.evaluate(..., base_nominal=...)` is converted to intents via the existing `plan_to_intents()` and submitted through `RiskManager.check_order()` → `OrderManager`.
5. Docs: add `§29 MVP-6.11` to `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` recording C1–C5, sources, and boundaries.

## Tests (focused, `backend/tests/test_mvp611_deposit_sizing.py`)

1. SIMPLE: `D=10000, n=3, martingale=20%` → nominals `2747.25…, 3296.70…, 3956.04…` (sum == D within Decimal precision).
2. SIMPLE without martingale: equal nominals `D/n`.
3. CUSTOM: nominals = `D × nominal_percent/100`; `Σ nominal_percent > 100` → explicit error.
4. SIGNAL: either sized with `n = levels` (if the engine already uses it as the order limit) or explicit sizing error — whichever the code establishes; the REPORT states which and why.
5. Sizing function is independent of `DCAGridEngine` math (existing DCA/Grid suites unchanged).
6. Lot rounding down; a level below 1 lot → whole entry blocked, error message contents.
7. Missing lot size / instrument / currency → blocked.
8. `Bot.deposit` `None` / `0` / negative → `SizingNotConfigured`; API validation.
9. `UNKNOWN` → no intents at all (MVP-6.9 regression).
10. `FLAT` (after successful reconciliation) + no active orders → entry intents submitted via Risk Manager.
11. `FLAT` + active bot orders → no entry.
12. Absent position without successful reconciliation → treated as `UNKNOWN`.
13. `OPEN` → no new grid/entry intents; exits unchanged (MVP-6.9 regression).
14. Sign mismatch → no intents.
15. Backtest suites unchanged; full suite green.

## Explicit constraints (AGENTS.md)

- Do not change `DCAGridEngine` mathematics, Veles Filter/Signal semantics, Backtest behaviour, `Decimal`/UTC handling, broker neutrality.
- T-Invest stays read-only in the live runtime: this MVP produces risk-gated intents; enabling real order submission in production is **out of scope**.
- No invented defaults: deposit, lot, currency, max order count, leverage.
- Any behaviour not covered by C1–C5 → stop at the boundary, document it in the REPORT, ask.

## Known gaps to record (do not fix in 6.11)

- Backtest sizing uses `BacktestConfig.quantity` (first-order units) while Live uses the deposit contract C2 → Live/Backtest sizing contracts differ. Record in REPORT; aligning them requires a separate task (spec principle: Backtest and Live share trading logic).
- `PROJECT_STATE.md` says "T-Invest order submission is not implemented", while `TInvestAdapter.place_order()` (PostOrder, MVP-6.2) exists. Clarify the wording in the REPORT (adapter implemented vs not enabled in the live runtime).
- Deal continuation across cycles (persisted grid state, averaging after entry) — separate MVP.
- Live cycle scheduling — separate MVP.

## Out of scope

Live cycle scheduler, production order submission enablement, leverage/margin, reinvest, deal continuation, multi-timeframe filters, Trailing, optimizer, UI redesign, Paper Trading, direct MOEX API.

## Validation & REPORT

Before reporting: full `pytest`, `ruff check app tests scripts`, `npm run build`, actual diff review against merge-base.

REPORT → `agent/control:.agent/REPORT-MVP-6.11.md` with: task, branch, commit SHA, exact changes, validation results, known limitations, documentation/specification gaps, AGENTS.md compliance.

Do not publish to `master`. Do not self-declare acceptance. Acceptance is by independent review.

## Correction round 1 (review 2026-09-29)

Review: `.agent/REVIEW-MVP-6.11.md` — **REJECTED**, one blocking finding (B1): exits of an OPEN position are blocked by entry-sizing errors (`SizingNotConfigured` / `SignalSizingUnsupported` / `CustomDepositExceeded`). Fix exactly as described in the review: resolve the C2 sizing only on the FLAT entry path, add the listed regression tests, update `§29`. REPORT → `.agent/REPORT-MVP-6.11-REV1.md`.

## Publication (mandatory, see `.agent/OPENCODE-WORKFLOW.md` → "Mandatory push rule")

```
git push origin agent/review/mvp-6.11
git push origin agent/control
git ls-remote origin agent/review/mvp-6.11 agent/control
```

No `--force`, no rebase; if rejected: `git fetch origin`, `git merge origin/<branch>`, push again. The REPORT must cite the pushed SHA ("pushed, in sync with origin"). Never push `master`.
