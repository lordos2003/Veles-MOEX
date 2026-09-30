# Veles-MOEX — Project State

## Project
- Repository: `lordos2003/Veles-MOEX`
- Goal: Veles-like web trading application for MOEX using T-Invest as the initial broker integration.
- Initial broker boundary: no direct MOEX API. `TInvestAdapter.place_order()` (PostOrder, MVP-6.2) exists behind `RiskManager -> OrderManager`, but no live strategy cycle is scheduled/enabled in production yet (see Known boundaries).

## Canonical workflow
`agent/control -> agent/review/mvp-X -> independent ChatGPT review -> master`

- `agent/control` is the canonical control/audit source.
- New tasks, audits and reviews start from the current `agent/control`.
- OpenCode implements only on the assigned `agent/review/mvp-X` branch.
- OpenCode must not publish to `master`.
- Only independently accepted work is published to `master`.
- `PROJECT_STATE.md`, current task, review and reports are maintained on `agent/control`; accepted records are mirrored to `master` for repository recovery.

## Current task

### MVP-6.11 — Bot Deposit Sizing & Entry from Confirmed Flat
**Status: IN REVIEW — round 2, correction committed and pushed, awaiting decision.**

- Reviewed: `e036c0e`; review record: `.agent/REVIEW-MVP-6.11.md`; report: `.agent/REPORT-MVP-6.11.md`; correction report: `.agent/REPORT-MVP-6.11-REV1.md`
- B1 (round-1 rejection): exits of an OPEN position must not depend on entry sizing (deposit / SIGNAL / CUSTOM errors blocked the TP) — corrected: sizing is resolved on the FLAT entry path only.
- C7 (carry-over, Issue #3): trim the market snapshot to exactly the latest `lookback_bars` candles — implemented; Issue #3 stays open until publication to `master`.
- C6 (owner decision 2026-09-29, Veles semantics): deposit edits apply from the next deal — deposit is read at each FLAT entry; an open deal is unaffected. Implemented; the deposit key is required on PATCH (a PATCH without it is 422, not a silent clear).

- Control task: `.agent/TASK-MVP-6.11-BOT-DEPOSIT-SIZING.md`
- Implementation branch: `agent/review/mvp-6.11` (from `master` @ `10d445e`)
- Closes the two remaining blockers of the live path: no sizing source (`SizingNotConfigured`) and the MVP-6.9 gate blocking entry from a flat position.
- New contracts C1–C5 (deposit semantics, deposit → order nominals, MOEX lot rounding down, confirmed-flat entry, `Bot.deposit`) approved by the project owner on 2026-09-29.

## Current accepted MVP

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
- **correction (2026-09-30):** snapshots are NOT yet trimmed to exactly `lookback_bars` (may return `lookback_bars + 1`); fix tracked by Issue #3, delivered as C7 in the MVP-6.11 correction round;
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
Work is delivered only when `agent/review/mvp-X` and the REPORT on `agent/control` are pushed to GitHub (plain push, no `--force`/rebase). See `.agent/OPENCODE-WORKFLOW.md` → "Mandatory push rule". `AGENTS.md` (on `master`) receives the same rule with the next publication.

## Recovery
For a new ChatGPT/OpenCode session:
1. Start from `agent/control`.
2. Read `PROJECT_STATE.md`.
3. Read the current `.agent/TASK-*.md`, applicable `.agent/REVIEW-*.md`, and latest `.agent/REPORT-*.md`.
4. Check current Git branch/HEAD and compare with `master` when required.
5. Continue from the accepted MVP and current control task; do not reconstruct state from chat history.
