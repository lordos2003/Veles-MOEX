# Veles-MOEX — Project State

Canonical recovery source: `agent/control`.

Current accepted MVP: **MVP-6.10 — Live Market Snapshot & Per-Bot Timeframe**.

- Accepted implementation: `c7429fdee1792962a679f1924230d99c62573efc`
- Publication PR: #4
- Publication merge commit: `14168ca798c00b8a28ef278bb245391a07bce958`
- Control task: `.agent/TASK-MVP-6.10-MARKET-SNAPSHOT.md`
- Control review: `.agent/REVIEW-MVP-6.10.md`
- Control report: `.agent/REPORT-MVP-6.10.md`

MVP-6.10 explicitly provides broker-neutral live market snapshots and per-bot timeframe propagation. Round-2 corrections removed inferred indicator warmup semantics in favor of explicit `StrategyConfig.lookback_bars` and enforce exact snapshot lookback.

Validation recorded: `pytest 369 passed, 1 skipped`; `ruff check app tests scripts` passed; `npm run build` passed.

MVP-6.9 remains accepted: `PositionManager` is the authoritative live execution quantity source and unresolved position state blocks live intents.

Known boundaries: T-Invest order submission is not implemented; live cycle scheduling is outside MVP-6.10; multi-timeframe filter series require separate specification; live production sizing remains governed by the accepted PositionManager boundary.

Workflow: `agent/control -> agent/review/mvp-X -> independent ChatGPT review -> master`. OpenCode does not publish directly to `master`.