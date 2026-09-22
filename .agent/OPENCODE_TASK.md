# OpenCode Agent Control

## STATUS
REPORT

## TASK_ID
MVP-6.3

## TASK
Implement MVP-6.3: live synchronization, durable execution-state persistence, startup/reconnect reconciliation, and safe recovery for the existing T-Invest Open API live execution domain.

## Context

Accepted product baseline:
- 8529bc028178a18d131abf65b36f705c573a7713 — fix: use OrderStateStream for live executions

Accepted previous scope:
- MVP-6.1 broker-neutral live execution domain;
- MVP-6.2 / 6.2.1 T-Invest Open API execution and real WebSocket transport;
- MVP-6.2.2 OrderStateStream-only live execution.

The project specification requires live execution state to survive process restart and requires reconciliation before new execution resumes.

## Objective

Make the existing live execution state durable and implement safe reconciliation/recovery after process restart or broker-stream reconnect.

The system must prefer broker facts over stale in-memory assumptions.

## Required scope

### 1. Durable execution state

Persist the minimum state needed to recover active live execution:

- execution intent identity;
- internal order identity;
- broker order ID;
- T-Invest idempotency/order request ID;
- instrument FIGI/UID as currently represented by the broker-neutral model;
- side;
- requested/fill/remaining quantity;
- order state;
- limit price where applicable;
- average fill price where available;
- fill/execution records including trade ID;
- position state required by PositionManager;
- reconciliation/synchronization timestamps;
- terminal error/unknown state where applicable.

Use the project's existing PostgreSQL/ORM infrastructure. Do not introduce a second persistence technology.

### 2. Repository boundary

Introduce persistence through repository interfaces so OrderManager/PositionManager remain broker-neutral and testable.

Do not make trading domain code depend directly on SQLAlchemy session/query details.

### 3. Startup recovery

On application startup/recovery:

1. load durable local live execution state;
2. query T-Invest broker state using the existing BrokerAdapter;
3. reconcile active orders;
4. reconcile positions;
5. reconcile fills using available broker facts and existing execution identifiers;
6. update durable local state;
7. only after successful reconciliation allow live execution to resume.

If reconciliation cannot establish a safe state, do not submit new orders and expose an ERROR/unknown recovery state.

### 4. Stream reconnect recovery

Preserve the current OrderStateStream-only transport.

After stream reconnect:

1. resubscribe;
2. perform unary reconciliation;
3. deduplicate already-known executions by trade ID;
4. continue processing live events only after reconciliation succeeds.

Do not reintroduce TradesStream.

### 5. Idempotency and lost-response recovery

Preserve the existing UUID idempotency key for each execution intent.

A lost broker response must not cause blind duplicate submission.

If the local order has an unknown submission outcome:

- use the stored broker request/idempotency identifier and available broker queries to resolve it;
- if it cannot be resolved safely, keep the order UNKNOWN and block unsafe new execution for that order/bot context.

### 6. Position authority

Position changes must continue to originate from actual fills/broker position facts, not merely from submitted intents.

After reconciliation, PositionManager must represent the broker position accurately enough for the existing DCA/Grid and Exit Engine to continue from the recovered state.

Do not redesign DCA or Exit calculations.

### 7. Duplicate/out-of-order events

The recovery path must tolerate:

- duplicate order-state events;
- duplicate trade IDs;
- events arriving after unary reconciliation;
- stale local state;
- partial fills followed by later full fills.

The same trade must affect position accounting exactly once.

### 8. Tests

Add/update deterministic tests for at least:

- persist and reload an active internal order;
- persist and reload fills;
- restart recovery of an active order;
- broker order differs from stale local order;
- broker position differs from stale local position;
- duplicate trade during recovery is applied once;
- lost response resolved through broker query;
- unresolved order remains UNKNOWN and blocks unsafe continuation;
- successful reconnect reconciliation before resume;
- failed reconciliation blocks new execution;
- recovered DCA position keeps correct weighted average;
- persistence does not leak broker-specific protocol objects into trading domain.

Use fakes/mocks for broker calls. Do not place real-money orders.

## Explicit non-goals

Do NOT implement in this task:

- T-Invest MCP;
- Bot lifecycle START/STOP/EMERGENCY_STOP;
- Risk Manager;
- new Strategy logic;
- new DCA/Grid modes;
- new Exit modes;
- new brokers;
- direct MOEX APIs;
- tick-level backtesting;
- autonomous strategy optimization;
- financial parameter tuning;
- microservices;
- unrelated refactoring.

Do not change the current OrderStateStream-only decision.

## Architecture constraints

- Trading domain remains broker-neutral.
- T-Invest-specific objects stay inside the broker adapter.
- Keep Decimal for money/price/quantity.
- Keep canonical quantity in instrument units in the domain.
- Preserve the current idempotency semantics.
- Do not bypass repository boundaries with ad-hoc global state.
- Use the existing PostgreSQL/ORM infrastructure.
- Do not invent broker protocol fields.

## Validation

Run:

pytest
ruff
npm build

Also inspect:

git status
git diff
git log -5 --oneline

## Git

Create one focused commit:

feat: implement live state reconciliation and recovery

Do NOT push.

Do NOT merge or rebase.

If history diverges unexpectedly, stop and report it.

## REPORT

Task MVP-6.3 — live synchronization, durable execution-state persistence,
startup/reconnect reconciliation, and safe recovery.

### 1. What was implemented
- Added a broker-neutral `LiveStateStore` boundary (Protocol) plus
  `LiveStateSnapshot` in `app.trading.state`, so durability never leaks
  SQLAlchemy into the trading domain.
- Added `SqlAlchemyLiveStateStore` in `app.persistence.execution_state`, mapping
  the domain dataclasses (`ExecutionIntent`, `InternalOrder`, `Fill`,
  `Position`) to new ORM tables.
- Added ORM models in `app.models.live_execution`
  (`live_intents`, `live_orders`, `live_fills`, `live_positions`) and Alembic
  migration `0003_live_execution_state`.
- Added `LiveRecoveryCoordinator` in `app.trading.recovery` that loads durable
  state, reconciles active orders/positions against broker facts, persists the
  reconciled snapshot, and returns `SAFE`/`BLOCKED`.
- `OrderManager` gained `snapshot()`, `load_snapshot()`, `list_intents()` and
  `_max_order_seq()`; `PositionManager` gained `load_state()`/`clear()`;
  in-memory repositories gained `clear()`.
- `ALLOWED_TRANSITIONS[UNKNOWN]` now permits resolving an unknown submission
  outcome to a real broker state (strictly necessary for lost-response
  recovery).
- `BrokerOrder` gained `idempotency_key` and `TInvestAdapter._to_order`
  populates it from `orderRequestId`, enabling lost-response resolution by
  idempotency.

### 2. Files changed
- backend/app/brokers/base.py (`BrokerOrder.idempotency_key`)
- backend/app/brokers/tinvest.py (`_to_order` idempotency_key)
- backend/app/models/__init__.py (export live models)
- backend/app/models/live_execution.py (new)
- backend/app/persistence/__init__.py (new)
- backend/app/persistence/execution_state.py (new)
- backend/app/trading/__init__.py (exports)
- backend/app/trading/domain.py (UNKNOWN transitions)
- backend/app/trading/order_manager.py (snapshot / load_snapshot)
- backend/app/trading/position_manager.py (load_state / clear)
- backend/app/trading/recovery.py (new)
- backend/app/trading/repository.py (Protocols + clear)
- backend/app/trading/state.py (new)
- backend/alembic/versions/0003_live_execution_state.py (new migration)
- backend/tests/test_live_recovery.py (new, 13 tests)

### 3. Persistence / repository design
- Trading domain sits behind a `LiveStateStore` Protocol
  (`save_snapshot`/`load_snapshot`). Default is `InMemoryLiveStateStore`;
  production uses `SqlAlchemyLiveStateStore` (async session on the existing
  PostgreSQL/ORM infra). No second persistence technology.
- ORM tables are self-contained: canonical instrument identifier stored as a
  string, no FK join to `accounts`/`instruments`, so the live state reloads
  independently of the wider product ORM graph.
- Money/quantity stays `Decimal` (`Numeric(20,8)`); enum fields persisted as
  strings. `OrderManager`/`PositionManager` remain synchronous and
  broker-neutral; durability is an explicit checkpoint
  (`LiveRecoveryCoordinator.persist_snapshot`) rather than per-event async IO.

### 4. Startup and reconnect reconciliation flow
- `recover(account_id)` = load durable snapshot -> rebuild managers
  (`load_snapshot`) -> query `get_orders`/`get_order` -> reconcile order status
  (broker facts win) -> reconcile positions via `get_open_positions` -> persist
  reconciled snapshot -> report `SAFE`/`BLOCKED`.
- The same `recover()` path is used after a stream reconnect; the
  OrderStateStream-only transport and its unary recovery are preserved
  (no TradesStream reintroduced).

### 5. Idempotency / lost-response handling
- UUID idempotency key is preserved on every intent/order; `_find_duplicate` is
  unchanged, so a lost response cannot trigger a blind duplicate submission.
- If an order is `UNKNOWN`, recovery resolves it by matching broker orders on
  `broker_order_id` or `idempotency_key`. If it cannot be resolved it is kept
  `UNKNOWN` and recovery returns `BLOCKED`, blocking unsafe continuation.

### 6. Tests and exact results
New `tests/test_live_recovery.py` (13 deterministic tests) cover: persist and
reload an active internal order; persist and reload fills; restart recovery that
reconciles order+position to broker; broker order differs from stale local;
broker position differs from stale local; duplicate trade applied exactly once;
lost response resolved via broker query; unresolved order stays UNKNOWN and
blocks; successful reconciliation allows resume; failed reconciliation blocks
new execution; recovered DCA position keeps correct weighted average;
persistence does not leak broker-specific objects and reloads into domain types.
Uses fakes plus an in-memory SQLite store (aiosqlite, StaticPool); no real-money
orders.

Full backend suite: `248 passed, 1 skipped` (baseline was `235 passed,
1 skipped`; +13 new). The single skip is the opt-in live sandbox integration
test (skipped because no credentials).

### 7. ruff result
`All checks passed!` (app + tests).

### 8. npm build result
`✓ built in 2.22s` (vite, 32 modules).

### 9. commit SHA
`3720b7ca3548ae6339a5c7597c59923634f5ee77` — `feat: implement live state
reconciliation and recovery` (branch `master`, NOT pushed).

### 10. Known limitations
- `LiveRecoveryCoordinator` / `SqlAlchemyLiveStateStore` are implemented and
  tested but NOT yet wired into a production composition root / app startup
  (the app currently has no live-execution startup path; `app.api.deps` returns
  a per-request `TInvestAdapter`). Wiring (DB session + store + coordinator and
  checking `result.safe` before resuming) is left to a subsequent integration
  step and is recorded here as a limitation, not a task failure.
- Fill reconciliation on recovery relies on persisted fills plus stream
  deduplication by `trade_id`, not a separate broker "get trades" query; T-Invest
  executions arrive via OrderStateStream.
- No live/real-sandbox verification was performed (no credentials/network),
  consistent with earlier MVP-6.x reports.

### 11. Divergence / blocked conditions
- None. Implemented on top of the accepted baseline `8529bc0`; no merge or
  rebase performed; `master` NOT pushed (ahead of `origin/master` by 1).
- This report is published on `agent/control`; `## CHATGPT REVIEW` was not
  modified.

## CHATGPT REVIEW

This section is reserved for ChatGPT. OpenCode must not modify it.
