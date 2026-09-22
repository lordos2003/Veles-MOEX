# OpenCode Agent Control

## STATUS
READY

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

OpenCode must replace this section with a complete implementation report after the task is finished.

The report must include:
1. what was implemented;
2. files changed;
3. persistence/repository design;
4. startup and reconnect reconciliation flow;
5. idempotency/lost-response handling;
6. tests and exact results;
7. ruff result;
8. npm build result;
9. commit SHA;
10. known limitations;
11. any divergence or blocked condition.

## CHATGPT REVIEW

This section is reserved for ChatGPT. OpenCode must not modify it.
