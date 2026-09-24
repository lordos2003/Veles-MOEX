# Veles-MOEX — REPORT: MVP-6.7 Strategy → Bot Runtime → Trading Engine

## Implementation commit

`57b192dfe5e20b744eb7441c3c2769d6e38d6db0` — "feat: implement MVP-6.7 strategy ->
bot runtime -> trading engine" (single focused commit on `master`).

Note: the task's base commit was `b2b199e`; the implementation was made on the
current accepted `master` (`3231a51`, which includes the accepted MVP-6.6 Risk
Manager preconditions the task builds on).

## Exact files changed

Added:

- `backend/app/bots/strategy.py` — `StrategyLoadError`, immutable
  `BotStrategy`, `load_bot_strategy()`, `load_bot_strategy_by_id()`.
- `backend/app/trading/plan_intent.py` — `plan_to_intents()` (Plan ->
  `ExecutionIntent` conversion at the orchestration boundary).
- `backend/tests/test_strategy_live_integration.py` — 12 focused tests for the
  new MVP-6.7 contracts.

Modified:

- `backend/app/trading/bot_lifecycle.py` — async `BotRuntime.start()` with
  per-bot strategy load; `BotRuntime.execute_strategy(MarketContext)`;
  `BotRuntimeManager.start()` awaits the runtime.
- `backend/app/trading/engine.py` — `compose_strategy_engine()` production
  composition; `TradingEngine.process()` submits every intent returned by the
  `intent_factory` (single intent or list) through `submit_intent`.
- `backend/app/trading/live_execution.py` — `build_live_service()` wires the
  per-bot strategy loader and per-bot `TradingEngine`.
- `backend/app/api/bots.py` — explicit 409 start failure on
  `StrategyLoadError` (state persisted as ERROR).
- `backend/app/bots/__init__.py`, `backend/app/trading/__init__.py` — exports.
- `backend/tests/test_bot_lifecycle.py` — `runtime.start()` call sites updated
  to `await` (start is now async because it loads the strategy); behavior
  assertions unchanged.
- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` — section 25 (MVP-6.7
  boundary documentation).

## Exact StrategyVersion loading path

`app/bots/strategy.py` is the minimum repository/service boundary:

1. `load_bot_strategy_by_id(session, bot_id)` loads the `Bot` row.
2. `load_bot_strategy(session, bot)` loads the referenced
   `StrategyVersion` (`session.get(StrategyVersion, bot.strategy_version_id)`),
   reads its immutable JSONB `config`, and validates it with
   `StrategyConfig.model_validate(...)`.
3. Result: frozen `BotStrategy(strategy_version_id, version, config)`.

Missing version or invalid configuration raises `StrategyLoadError` — no
second strategy storage model, no mutation of `StrategyVersion`, no invented
defaults.

## StrategyEngine composition

`compose_strategy_engine()` (app/trading/engine.py) constructs the existing
`EntryEngine`, `DCAGridEngine`, `ExitEngine` into a shared broker-neutral
`StrategyEngine` without altering their calculations. Each bot runtime composes
its **own** `TradingEngine` on START with **its own** immutable
`StrategyConfig` (no global strategy configuration).

## MarketContext source/boundary

`MarketContext` is the broker-neutral input to
`BotRuntime.execute_strategy(context)` — always injected explicitly by the
caller. There is currently **no production market-data source wired** into the
runtime; no hardcoded prices, no fake candles, no fake positions. Wiring a live
MarketContext source is an explicit follow-up boundary (documented in
TASK-09 §25 and the `build_live_service()` docstring).

## Lifecycle behavior

`BotRuntime.start()` (now async):

1. STOPPED/ERROR -> STARTING;
2. load the bot's own strategy (fail -> ERROR + `StrategyLoadError`, re-raised;
   the RiskManager slot is never consumed because `start_bot()` runs only
   after the load succeeds);
3. compose the per-bot `TradingEngine` (started);
4. `RiskManager.check_start()` (rejected -> ERROR + `BotStartRejected`);
5. `start_bot()` -> RUNNING.

`execute_strategy(context)` is gated on RUNNING (otherwise `BotStateError`).
All MVP-6.5 semantics are preserved: STOP ordering, cancellation-failure ->
ERROR before slot release, EMERGENCY_STOP, restart restore to ERROR, explicit
START after restart, rejected START persists ERROR, no disconnected fallback
manager. The API reports a failed strategy start as an explicit 409 and
persists ERROR.

## ExecutionIntent conversion

`plan_to_intents()` (app/trading/plan_intent.py), at the Trading Engine /
runtime orchestration boundary:

- **DCA/Grid orders** (`GridOrder`) are converted: real domain quantity/price;
  `order_type` = LIMIT when a price exists, MARKET otherwise; `bot_id`,
  `instrument_figi` (loaded from the `Instrument` row) and the account's
  `external_account_id` are set; `intent_id` is a deterministic content hash
  (bot_id, index, side, quantity, price) so repeated identical plans map to
  the same intent — existing `ExecutionIntent` idempotency semantics intact
  (verified by test).
- **Entry signals** are NOT converted: the domain carries no order quantity
  (explicit boundary).
- **Exit plans** are NOT converted: the quantity originates from the
  `position_qty=1.0` placeholder in `StrategyEngine.evaluate()` (explicit
  boundary; a live exit quantity must come from real position state).

The Strategy Engine code never imports or calls the OrderManager; all
submissions go `TradingEngine.process() -> submit_intent() ->
RiskManager.check_order() -> OrderManager.submit()`.

Per-bot risk configuration limitation: `StrategyConfig.risk` is NOT copied
into the execution RiskManager; the production RiskManager uses only the typed
application settings (`risk_*`). No precedence rules invented (documented in
TASK-09 §25 and `build_live_service()` docstring).

## Tests

`backend/tests/test_strategy_live_integration.py` — 12 focused tests for the
new contracts (per the updated task scope; restart semantics and full
MVP-6.5/6.6 regression are covered by the existing suites, not duplicated):

1. valid Bot -> StrategyVersion -> StrategyConfig;
2. missing StrategyVersion rejected;
3. invalid StrategyVersion config rejected;
4. failed strategy load -> bot ERROR;
5. failed strategy load does not consume the concurrent-bot slot;
6. valid strategy cannot execute while the bot is not RUNNING;
7. strategy plan reaches the TradingEngine end-to-end (order created with
   correct figi/bot/account/type/price/quantity; this is also the coverage for
   "no direct StrategyEngine -> OrderManager submission path");
8. RiskManager rejects before the OrderManager (no broker call);
9. duplicate plan evaluation is idempotent (stable intent id -> one order);
10. entry signal without quantity is not converted;
11. exit placeholder quantity is not converted;
12. no fabricated MarketContext in the trading code.

**Result: `pytest tests` → 323 passed, 1 skipped** (full suite, including the
unchanged-behavior MVP-6.5 lifecycle and MVP-6.6 risk tests).

## Lint / build

- `ruff check app tests scripts` → **All checks passed!**
- `npm run build` (frontend) → **✓ built in 7.49s**

## Git state

- Implementation commit: `57b192dfe5e20b744eb7441c3c2769d6e38d6db0` on local
  `master`.
- Published on `agent/review/mvp-6.7` (HEAD = `57b192d`).
- `origin/master` NOT pushed (still `3231a51`, the accepted MVP-6.6 state);
  no merge/rebase performed.
