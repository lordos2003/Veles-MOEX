# Veles-MOEX — Project State

## Project
- Repository: `lordos2003/Veles-MOEX`
- Goal: Veles-like web trading application for MOEX using T-Invest as the initial broker integration.
- Initial broker boundary: T-Invest read-only; no direct MOEX API and no live order submission in current MVP.

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
**Status: OPEN — assigned to OpenCode.**

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
- market snapshots preserve exactly the latest configured `lookback_bars` candles;
- MVP-6.9 position-state invariant remains intact.

Validation recorded for MVP-6.10: `pytest 369 passed, 1 skipped`; `ruff check app tests scripts` passed; `npm run build` passed.

Known boundaries:
- T-Invest order submission is not implemented;
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
- `TInvestAdapter` provides read-only access through the official REST API.
- Domain prices/monetary values use `Decimal`.
- Market timestamps are timezone-aware UTC.
- Instrument identity uses FIGI.
- `MarketCandle` uniqueness: `(figi, timeframe, timestamp)`.
- Veles Filter/Signal semantics: Argument1 + Operator + Argument2; AND within group, OR between groups; state operators `>`/`<`, event operators for crossings.
- DCA/Grid and Backtest semantics are preserved across live-market-data work.

## Recovery
For a new ChatGPT/OpenCode session:
1. Start from `agent/control`.
2. Read `PROJECT_STATE.md`.
3. Read the current `.agent/TASK-*.md`, applicable `.agent/REVIEW-*.md`, and latest `.agent/REPORT-*.md`.
4. Check current Git branch/HEAD and compare with `master` when required.
5. Continue from the accepted MVP and current control task; do not reconstruct state from chat history.
