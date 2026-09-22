# OpenCode Agent Control

## STATUS
READY

## TASK_ID
MVP-6.2.2

## TASK
Switch live T-Invest execution to OrderStateStream only.

Current product commit:
5d52014 — feat: connect real T-Invest Open API transport

### Objective
Use only T-Invest OrderStateStream as the live WebSocket stream for order and execution events.

Do not use TradesStream in the live transport.

### Why
- OrderStateStream.orderState.trades[] already contains individual executions:
  tradeId, dateTime, price, quantity.
- T-Bank Dev Portal currently marks TradesStream as deprecated and recommends OrderStateStream.
- Documentation does not confirm multiplexing OrderStateStream and TradesStream over the current single WebSocket connection.
- The current implementation sends two identical subscribe frames over one connection, which is not sufficiently verified.

### Required changes
1. In TInvestWebSocketStreamTransport:
   - keep one real WebSocket connection;
   - send only one OrderStateStream subscription;
   - do not send a second identical subscription;
   - process orderState events;
   - ignore ping/subscription envelopes as before;
   - handle rpcStatus errors.
2. Convert orderState.trades[] into existing broker-neutral TradeFill events.
3. Preserve trade_id deduplication.
4. Keep existing order lifecycle mapping:
   NEW -> SUBMITTED/WORKING
   PARTIALLYFILL -> PARTIALLY_FILLED
   FILL -> FILLED
   REJECTED -> REJECTED
   CANCELLED -> CANCELLED
5. Preserve reconnect and unary reconciliation:
   reconnect -> OrderStateStream subscription -> GetOrders/GetOrderState/GetPositions.
6. Do not add PostgreSQL persistence or process-restart recovery.
7. Do not change Strategy, DCA, Exit Engine, Risk Manager, or trading domain unless strictly necessary.
8. Do not change the WS URL speculatively. Keep the current documented endpoint if it is already correct.
9. Do not invent fields such as streamId/service/channel/subscriptionAction unless required by the actual OrderStateStream contract.
10. Remove obsolete live TradesStream assumptions and tests.

### Tests
Run and update tests for:
- one WS connection;
- one subscribe request;
- account + pingDelayMs;
- Bearer authentication;
- orderState parsing;
- orderState.trades[] -> TradeFill;
- duplicate tradeId applied exactly once;
- NEW/PARTIALLYFILL/FILL/REJECTED/CANCELLED;
- reconnect and re-subscription.

Run:
pytest
ruff
npm build

### Documentation
Update:
docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md

State that MVP live execution uses OrderStateStream and executions come from orderState.trades[]. Do not claim TradesStream is technically impossible; state only that it is not used and why.

### Git
Do NOT push.
Create one focused commit:
fix: use OrderStateStream for live executions

Before committing:
git status
git diff
git log -5 --oneline

If history diverges unexpectedly, stop and report it. Do not merge/rebase.

## REPORT
Write the complete execution report below this heading when the task is finished.

Include:
1. What changed.
2. Files changed.
3. Tests added/changed.
4. pytest result.
5. ruff result.
6. npm build result.
7. Commit SHA.
8. Any remaining limitation or uncertainty.
9. Confirm that push was NOT performed.

## CHATGPT REVIEW
This section is reserved for ChatGPT. OpenCode must not modify it.
