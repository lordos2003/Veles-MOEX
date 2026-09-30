# Veles-MOEX — Project State

## Project
- Repository: `lordos2003/Veles-MOEX`
- Goal: Veles-like web trading application for MOEX using T-Invest as the initial broker integration.
- Initial broker boundary: no direct MOEX API. `TInvestAdapter.place_order()` (PostOrder, MVP-6.2) exists behind `RiskManager -> OrderManager`, but no live strategy cycle is scheduled/enabled in production yet (see Known boundaries).

## Canonical workflow
`agent/control -> agent/review/mvp-X -> independent review (ChatGPT / Claude) -> master`

- `agent/control` is the canonical control/audit source.
- New tasks, audits and reviews start from the current `agent/control`.
- Кодер implements only on the assigned `agent/review/mvp-X` branch.
- Кодер must not publish to `master`.
- Only independently accepted work is published to `master`.
- `PROJECT_STATE.md`, current task, review and reports are maintained on `agent/control`; accepted records are mirrored to `master` for repository recovery.

## Current task

### MVP-6.12 — Live Deal Continuation (Simple TP, Simple/Custom grid)
**Status: ACCEPTED (round 3, 2026-09-30) — awaiting publication to `master`.** Accepted implementation `418c24e`; review `.agent/REVIEW-MVP-6.12.md` (rounds 1–3); validation 450 passed, 1 skipped.

- Reviewed: `a4f792d`; review: `.agent/REVIEW-MVP-6.12.md`; reports: `.agent/REPORT-MVP-6.12.md`, `.agent/REPORT-MVP-6.12-REV1.md`, `.agent/REPORT-MVP-6.12-REV2.md`
- Correction round 1: `949bebe` (B1 risk-gate before TP cancel + per-event pump isolation; B2 deal errors → bot ERROR via lifecycle + `deal_error` in `GET /api/bots/{id}` + OPEN-without-Deal → ERROR; D7 reducing-intent exemption in `RiskManager`; review observation 2 regression test). Validation: pytest 447 passed/1 skipped, ruff clean, alembic single head `0005_deal_continuation`, npm build green.
- Correction round 2: `418c24e` (B3: fills accepted in `CANCEL_REQUESTED` and for already-`CANCELLED` orders (terminal state kept, fill still applied to position/record); `_rearm_tp()` re-reads the position after the cancel and rebuilds the TP from the actual facts — never exceeding the position, zero → close; `recover()` no longer re-registers a Deal closed during recovery; 3 B3 tests). Validation: pytest 450 passed/1 skipped, ruff clean, alembic single head `0005_deal_continuation`, npm build green.

- Control task: `.agent/TASK-MVP-6.12-DEAL-CONTINUATION.md`
- Implementation branch: `agent/review/mvp-6.12` (from `master` @ `59a3897`)
- Contracts D1–D7 approved by the project owner 2026-09-30: supported live configuration only (SIMPLE/CUSTOM + Simple TP, others rejected at START); event-driven deal lifecycle; tick rounding in the safe direction; TP from the average price, re-armed on every grid fill; durable Deal + recovery; the live cycle no longer produces exits; position-reducing orders exempt from growth limits (D7).
- Next after 6.12: live cycle scheduler; Multi-Take / break-even / Signal TP / stop-loss / pull-up / SIGNAL mode.

## Current accepted MVP

### MVP-6.11 — Bot Deposit Sizing & Entry from Confirmed Flat
**Status: ACCEPTED (round 3, 2026-09-30) and published to master.**

- Accepted implementation: `e026886dfdc6f98112dfc214060c5fc2bb2ae075`
- Publication PR: #6
- Publication merge commit: `40cf6ce802e685b99ae527758949e29a8a67d26d`
- Control task: `.agent/TASK-MVP-6.11-BOT-DEPOSIT-SIZING.md`
- Control review: `.agent/REVIEW-MVP-6.11.md` (round 1 REJECTED B1, round 2 REJECTED B2, round 3 ACCEPT)
- Reports: `.agent/REPORT-MVP-6.11.md`, `.agent/REPORT-MVP-6.11-REV1.md`, `.agent/REPORT-MVP-6.11-REV2.md`

Contracts (owner-approved 2026-09-29/30):
- C1/C5 `Bot.deposit` (bot setting, migration `0004_bot_deposit`, `GET/PATCH /api/bots/{id}`, `> 0`, `deposit` key required on PATCH);
- C2 sum of all grid-order nominals of a deal = deposit (SIMPLE `D/Σkⁱ`, CUSTOM `D×pct/100` with the >100% guard, SIGNAL blocked — no order limit invented); spot 1:1, no leverage;
- C3 MOEX lots rounded down; any level below one lot blocks the whole entry; missing lot/currency blocks;
- C4 live position state UNKNOWN / FLAT / OPEN / SIGN_MISMATCH, established only by a successful broker reconciliation; FLAT → entry only (no active bot orders); OPEN → exits only; others → nothing;
- C6 deposit edits apply from the next deal: fresh DB read (`populate_existing`) at each FLAT entry; an open deal is unaffected;
- C7 market snapshot trimmed to exactly `lookback_bars` (Issue #3);
- B1 exits of an open position never depend on entry sizing.

Validation (independent, clean env): `pytest 412 passed, 1 skipped`; `ruff check app tests scripts` passed; alembic single head `0004_bot_deposit`; `npm run build` passed (no frontend changes).

Known boundaries:
- no live cycle scheduler; the strategy cycle is triggered explicitly;
- no deal continuation: while OPEN only exits are produced; averaging after entry is not implemented;
- TP price is derived from the market-context price, not the average entry price (pre-existing);
- position state is per FIGI, not per bot (manual trades / several bots on one instrument share it);
- Backtest sizing (`BacktestConfig.quantity`) differs from the Live deposit contract C2;
- SIGNAL-mode live entry is blocked until an order-limit contract is approved.

### MVP-6.10 — Live Market Snapshot & Per-Bot Timeframe
**Status: ACCEPTED and published to master.**

- Accepted implementation: `c7429fdee1792962a679f1924230d99c62573efc`
- Publication PR: #4
- Publication merge commit: `14168ca798c00b8a28ef278bb245391a07bce958`
- Control task: `.agent/TASK-MVP-6.10-MARKET-SNAPSHOT.md`
- Control review: `.agent/REVIEW-MVP-6.10.md`
- Control report: `.agent/REPORT-MVP-6.10.md`

Round-2 corrections:
- removed inferred indicator warmup / `required_bars` semantics;
- introduced explicit `StrategyConfig.lookback_bars`;
- **correction (2026-09-30):** the exact `lookback_bars` trim was not in the MVP-6.10 code; delivered by MVP-6.11 C7 (PR #6, Issue #3 closed);
- MVP-6.9 position-state invariant remains intact.

Validation recorded for MVP-6.10: `pytest 369 passed, 1 skipped`; `ruff check app tests scripts` passed; `npm run build` passed.

Known boundaries:
- T-Invest order placement exists at adapter level (`TInvestAdapter.place_order`, MVP-6.2) behind Risk/Order Manager; production live trading is not enabled (no scheduled live cycle, no deal continuation);
- live cycle scheduling is outside MVP-6.10;
- multi-timeframe filter series require a separately specified implementation;
- authoritative production sizing remains governed by the accepted PositionManager boundary.

### MVP-6.9 — Position State & Authoritative Quantity
**Status: ACCEPTED and published.**
- Accepted review commit: `5b4c42be4d49d700e8750315c1da81b17bc04a1d`
- Publication PR: #2
- Publication merge commit: `cdc10296e32509f2d716c85c1b58e62a9b01b2cf`
- PositionManager is the authoritative live execution quantity source.
- Unresolved position state blocks all live ExecutionIntent creation/submission.

## Architecture
- Broker integration is behind `BrokerAdapter`.
- `TInvestAdapter` uses the official REST API: read access plus `PostOrder`-based `place_order` (MVP-6.2) behind the Risk/Order Manager.
- Domain prices/monetary values use `Decimal`.
- Market timestamps are timezone-aware UTC.
- Instrument identity uses FIGI.
- `MarketCandle` uniqueness: `(figi, timeframe, timestamp)`.
- Veles Filter/Signal semantics: Argument1 + Operator + Argument2; AND within group, OR between groups; state operators `>`/`<`, event operators for crossings.
- DCA/Grid and Backtest semantics are preserved across live-market-data work.

## Workflow rule: push before review
Work is delivered only when `agent/review/mvp-X` and the REPORT on `agent/control` are pushed to GitHub (plain push, no `--force`/rebase). See `.agent/CODER-WORKFLOW.md` → "Mandatory push rule". The same rule is in `AGENTS.md` §6 (published with MVP-6.11).

## Recovery
For a new ChatGPT/Кодер session:
1. Start from `agent/control`.
2. Read `PROJECT_STATE.md`.
3. Read the current `.agent/TASK-*.md`, applicable `.agent/REVIEW-*.md`, and latest `.agent/REPORT-*.md`.
4. Check current Git branch/HEAD and compare with `master` when required.
5. Continue from the accepted MVP and current control task; do not reconstruct state from chat history.
