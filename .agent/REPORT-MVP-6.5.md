# REPORT — MVP-6.5 Bot Lifecycle and Risk Preconditions

Task/status: `MVP-6.5-BOT-LIFECYCLE-FOUNDATION` — IMPLEMENTED.

Commit SHA: `9affc539a7653ab32e6517fe994f7b3f7cca5c03` (published on
`agent/review/mvp-6.5`).

## Exact lifecycle implementation

The MVP-6.5 task (the follow-up task after the audit) authorised a real,
broker-neutral bot lifecycle foundation. Implemented as the upstream control
layer:

`LiveExecutionService.submit()` -> `BotRuntime.submit_intent()` ->
`TradingEngine.submit_intent()` -> `RiskManager.check_order()` ->
`OrderManager.submit()` -> broker.

- `app/trading/bot_lifecycle.py` — `BotState` (STOPPED, STARTING, RUNNING,
  STOP_REQUESTED, ERROR, EMERGENCY_STOP), `ALLOWED_BOT_TRANSITIONS`,
  `BotRuntime` (per-bot state machine + execution gate) and `BotRuntimeManager`
  (registry/controller of the running application's bot runtimes).
- `app/models/enums.py` — added `BotState`.
- `app/models/bot.py` — `Bot.status` now defaults to `BotState.STOPPED.value`.
- `app/trading/domain.py` — added `bot_id` to `ExecutionIntent` and
  `InternalOrder` for bot->order correlation.
- `app/trading/order_manager.py` — `_new_order`/`_reject` propagate `bot_id`.
- `app/trading/live_execution.py` — `LiveExecutionService.submit()` gates on the
  owning bot being RUNNING when a `BotRuntimeManager` is wired;
  `build_live_service()` wires a `BotRuntimeManager` (runtime factory binds the
  shared `TradingEngine`/`OrderManager` as the submit/cancel path).
- `app/bots/repository.py` (`BotRepository`) — load/save/update Bot state via the
  existing ORM `Bot` model + `AsyncSession` (no new persistence subsystem).
- `app/api/bots.py` — broker-neutral endpoints:
  `GET /bots`, `GET /bots/{bot_id}`, `POST /bots/{bot_id}/start`,
  `POST /bots/{bot_id}/stop`, `POST /bots/{bot_id}/emergency-stop`.
- `app/api/deps.py` / `app/api/router.py` — wired bot deps + router.

## State transition table

| from | to |
|------|----|
| STOPPED | STARTING |
| STARTING | RUNNING / ERROR |
| RUNNING | STOP_REQUESTED / EMERGENCY_STOP / ERROR |
| STOP_REQUESTED | STOPPED / ERROR |
| ERROR | STARTING |
| EMERGENCY_STOP | STOPPED |

Invalid transitions raise `BotStateError`. START runs `RiskManager.check_start()`
before RUNNING and `start_bot()` on success; a rejected START transitions to
ERROR and raises `BotStartRejected`. Normal STOP and EMERGENCY_STOP call
`stop_bot()`; normal STOP leaves the position open.

## RiskManager integration
- START -> `check_start(bot_id)` then `start_bot(bot_id)`.
- normal STOP / EMERGENCY_STOP -> `stop_bot(bot_id)`.
- `check_order()` remains the authoritative order gate (emergency stop,
  position-size, daily-loss). No financial limits invented.

## API integration
Minimal broker-neutral endpoints added (no UI, no auth subsystem). They drive the
`BotRuntimeManager` and persist the resulting state via `BotRepository`.

## Changed files
`backend/app/api/bots.py` (new), `backend/app/bots/__init__.py`,
`backend/app/bots/repository.py`, `backend/app/bots/schemas.py` (new),
`backend/app/trading/bot_lifecycle.py` (new), `backend/app/api/deps.py`,
`backend/app/api/router.py`, `backend/app/models/__init__.py`,
`backend/app/models/bot.py`, `backend/app/models/enums.py`,
`backend/app/trading/__init__.py`, `backend/app/trading/domain.py`,
`backend/app/trading/live_execution.py`, `backend/app/trading/order_manager.py`,
`docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`,
`backend/tests/test_bot_lifecycle.py` (new).

## Remaining boundaries (documented, not production-integrated)
- Strategy -> TradingEngine `process()` path is NOT wired (no live
  `StrategyEngine`/`StrategyConfig` source in MVP-6).
- No production risk-limits configuration source: `build_live_service()` uses
  default empty `RiskLimits()` (no invented financial defaults).
- Per-bot order cancellation relies on `bot_id` on intents/orders; EMERGENCY_STOP
  cancels a bot's active orders only through the existing broker-neutral
  `OrderManager.cancel()` path when an `OrderManager` is wired.

## Validation
- `pytest`: **287 passed, 1 skipped**.
- `ruff check app tests scripts`: **All checks passed!**
- frontend `npm run build`: **✓ built in 12.06s**.

## Git status
- `agent/review/mvp-6.5` -> `9affc539a7653ab32e6517fe994f7b3f7cca5c03`.
- `master` NOT pushed (ahead by the one implementation commit); no merge/rebase/reset.

## Git log -5 (master)
```
9affc53 feat: implement MVP-6.5 bot lifecycle and risk preconditions
3ce159f docs: state MVP-6 live integration boundary in task spec
b4a1deb fix: document strategy-path boundary in production live composition
63ca560 fix: guard TradingEngine.process against missing strategy config
75e336f feat: integrate RiskManager and TradingEngine into live execution
```
