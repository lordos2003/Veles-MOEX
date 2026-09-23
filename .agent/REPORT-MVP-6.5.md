# REPORT — MVP-6.5 Bot Lifecycle and Risk Preconditions

Task/status: `MVP-6.5-BOT-LIFECYCLE-RISK` — STOPPED (no real bot lifecycle found).

Commit SHA: none — no product code change was made (see "Decision" below).

## Audit: existing bot/application lifecycle

I inspected the repository on `master` (`3ce159f`) for an existing bot
domain/model/service/API/configuration before writing any code.

### What exists
- `backend/app/models/bot.py` — `Bot` ORM model. It is **unused in production**.
  Its `status` column is a free `String(32)` with the docstring comment
  "Exact vocabulary TBD at MVP-6." It is only exercised by the ORM-mapping test
  `backend/tests/test_domain_models.py:66` (constructs a `Bot` row).
- `alembic/versions/0001_initial.py` — creates the `bots` table (columns
  `id`, `name`, `strategy_version_id`, `account_id`, `instrument_id`, `status`,
  `is_active`, `started_at`, `stopped_at`). No bot lifecycle enum tied to it.
- `backend/app/trading/risk_manager.py:88-99` — `check_start()`,
  `start_bot()`, `stop_bot()` exist but are **unwired** (an isolated
  `_active_bots` counter; nothing calls them; no bot entity is managed).
- `TradingEngine.start()/stop()` and `LiveExecutionService.start()/shutdown()`
  are **app/singleton** lifecycle flags (`_started`), not a per-bot lifecycle.
- `backend/app/api/` exposes **only read-only** endpoints (`health`,
  `tinvest`); there is no bot start/stop/status route.
- `core/config.py` has only `live_trading_enabled`; there is **no production
  risk-limits source** wired into `build_live_service()` (it uses default empty
  `RiskLimits()`).

### What does NOT exist (the missing foundation)
There is **no real bot lifecycle** in the repository:
1. No bot lifecycle state machine — no `START / RUNNING / STOP_REQUESTED /
   STOPPED / ERROR / EMERGENCY_STOP` states; `enums.py` defines only
   `OrderSide/OrderType/OrderStatus` (no bot-state enum).
2. No bot service / repository / CRUD layer (only `models/bot.py`; no
   `BotService`, `BotRepository`, `BotStore`, `BotLifecycle`).
3. No bot API — no start/stop/status endpoints anywhere.
4. No per-bot execution routing: `TradingEngine`, `LiveExecutionService`,
   `RiskManager` are singletons; there is no notion of many bots each owning a
   lifecycle.
5. No production bot-state connected to live execution —
   `build_live_service()` builds one singleton service with no bot scope.
6. No production `RiskLimits` source (the `RiskConfig.max_*` fields in
   `strategies/config.py` are strategy-config-only and not wired).

## Decision

Per the task instructions:
> "If no bot lifecycle exists at all, stop and report the exact missing
> foundation. Do not invent a fake lifecycle."
> "Do not create a duplicate Bot subsystem."
> "Do not write tests against a fake lifecycle created only for this task."

Because no real bot lifecycle exists, implementing one would require a
parallel Bot subsystem (state machine + service + repository + API + wiring) —
exactly what the task forbids. I therefore **stopped** and did **not** invent a
lifecycle. No product code, tests, documentation, or financial defaults were
added.

## Required next foundation (for a future MVP)
To close the genuine gap, the following real pieces must exist before a
broker-neutral bot lifecycle can be implemented:
- a bot lifecycle state machine + status enum;
- a bot service/repository that loads/persists bot state (the `Bot` model and
  `bots` table already exist as a foundation);
- per-bot execution routing (scope `RiskManager`/`TradingEngine` per bot);
- a bot start/stop API;
- a production risk-limits configuration source.

## Validation
No code was changed, so there is nothing new to validate. The repository on
`master` remains at the accepted MVP-6.4 state.

## Git status
- Working tree clean on `agent/control`.
- No commit on `agent/review/mvp-6.5` (no code change to review).
- `master` NOT pushed, no merge/rebase/reset.

## Git log -5 (master)
```
3ce159f docs: state MVP-6 live integration boundary in task spec
b4a1deb fix: document strategy-path boundary in production live composition
63ca560 fix: guard TradingEngine.process against missing strategy config
75e336f feat: integrate RiskManager and TradingEngine into live execution
fe59bdf Merge remote-tracking branch 'origin/master'
```
