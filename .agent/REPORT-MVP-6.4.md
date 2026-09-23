# REPORT — MVP-6.4 integration: RiskManager + TradingEngine

Task/status: `integration-trading-risk` — REPORT.

## Correction commit SHAs
- `b4a1deb5386eb9e2cbd3753f14eebac13deba0e7` — `fix: document strategy-path boundary in production live composition`
- `3ce159f4ac2b49088a53ce70cd0d24a3f5a5b684` — `docs: state MVP-6 live integration boundary in task spec`

## Exact changes
- `backend/app/trading/engine.py`:
  - Added `TradingEngine.strategy_configured` property (`False` for production).
  - `process()` raises a `RuntimeError` when `strategy_engine`/`strategy_config` is `None` (explicit guard + error, not only a docstring).
  - `submit_intent()` remains risk-gated: `risk_manager.check_order()` then `order_manager.submit()`.
- `backend/app/trading/live_execution.py`:
  - `build_live_service()` annotated as execution-only composition with an explicit boundary docstring (the Strategy `process()` path is an integration seam, not wired in MVP-6).
- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`:
  - Added `### MVP-6 live integration boundary` documenting that the live runtime wires only the risk-gated execution path and that `TradingEngine.process()` (Strategy) and the bot-start lifecycle (`RiskManager.check_start()` / concurrent-bot control) are explicitly NOT wired in MVP-6. Contradictory "production-integrated" claims removed.

## Production execution path (verified)
`LiveExecutionService.submit()` (guard `if not self._safe: reject`) ->
`TradingEngine.submit_intent()` -> `RiskManager.check_order()` (raises `RiskRejected`) ->
`OrderManager.submit()` -> broker.
Recovery SAFE gate preserved.

## Strategy -> TradingEngine boundary
Not a production integration. No live `StrategyEngine`/`StrategyConfig` composition exists in MVP-6; the Strategy path is an integration seam. `TradingEngine.process()` raises if invoked without engine/config. No claim that this path is live-wired.

## max-concurrent-bots boundary
`RiskManager.check_start()` / `max_concurrent_bots` is an interface seam only. There is no wired bot-start lifecycle in MVP-6; bot-start / concurrent-bot start control is explicitly outside the MVP-6 scope. No fake lifecycle and no claim of authoritative live control.

## RiskLimits configuration status
Production `RiskManager` uses the default empty `RiskLimits` (no app-level risk-config source in MVP-6). No financial defaults were invented.

## Validation
- `pytest` (backend, `asyncio_mode="auto"`): **276 passed, 1 skipped**.
- `ruff check app tests scripts`: **All checks passed!**
- frontend `npm run build`: **✓ built in 2.54s**.

## Git status
- `master` is **4 commits ahead** of `origin/master` (`75e336f`, `63ca560`, `b4a1deb`, `3ce159f`); `master` NOT pushed; no merge/rebase performed.
- `origin/agent/review/mvp-6.4` -> `3ce159f` (publishes `3ce159f`; fast-forward `b4a1deb..3ce159f`). Verified by fetch: `3ce159f` is an ancestor of `origin/agent/review/mvp-6.4`.
- `origin/agent/control` -> this REPORT commit (`4c0c148` + report commit).

## Git log (master, last 5)
```
3ce159f docs: state MVP-6 live integration boundary in task spec
b4a1deb fix: document strategy-path boundary in production live composition
63ca560 fix: guard TradingEngine.process against missing strategy config
75e336f feat: integrate RiskManager and TradingEngine into live execution
fe59bdf Merge remote-tracking branch 'origin/master'
```
