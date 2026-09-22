# OpenCode Agent Control

## STATUS
REPORT

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

Task MVP-6.2.2 — Switch live T-Invest execution to OrderStateStream only.

### Divergence note (protocol)
The requested change is ALREADY implemented and committed on the product `master`
branch as `8529bc0 — fix: use OrderStateStream for live executions`. The current
working tree is checked out on branch `agent/control` at `509a019` (based on
`54e5b96`), which does NOT contain the MVP-6.2 / 6.2.1 work and therefore does not
have `TInvestWebSocketStreamTransport`. This diverges from the documented
"Current product commit: 5d52014". Per the protocol ("if history diverges
unexpectedly, stop and report; do not merge/rebase"), I did not re-apply or
merge; the report below documents the completed product change as it exists on
`master` (`8529bc0`).

1. What changed:
   - `TInvestWebSocketStreamTransport` opens one WebSocket connection and sends
     exactly ONE OrderStateStream subscription
     (`{"accounts":[...],"pingDelayMs":...}`); the second identical subscribe was
     removed. `rpcStatus` error frames surface as `BrokerConnectionError`
     (triggering reconnect); `ping`/`subscription` envelopes are ignored by the
     manager as before. TradesStream is not subscribed.
   - `TInvestStreamManager` now dispatches only `order_state` and `position`; the
     `order_trades` branch and the `_decode_trades` helper were removed. Individual
     executions are produced from `order_state.trades[]` -> `_trade_to_fill` ->
     `TradeFill` (trade_id, price, quantity in units, date_time, order identity).
     `trade_id` deduplication is preserved via `OrderManager.apply_fill`
     (`fill_id = trade_id`), so the same trade changes the position exactly once.
   - Order lifecycle mapping preserved:
     NEW->SUBMITTED, PARTIALLYFILL->PARTIALLY_FILLED, FILL->FILLED,
     REJECTED->REJECTED, CANCELLED->CANCELLED.
   - Reconnect / unary recovery preserved (manager unchanged): reconnect ->
     (re)subscribe OrderStateStream -> GetOrders / GetOrderState / GetPositions.
   - No Strategy/DCA/Exit/Risk/domain changes; no PostgreSQL persistence; no
     process-restart recovery; the WS URL was kept (not changed speculatively);
     no invented fields (streamId/service/channel/subscriptionAction).

2. Files changed:
   - backend/app/brokers/tinvest_stream_transport.py
   - backend/app/brokers/tinvest_streams.py
   - backend/tests/test_tinvest_stream_transport.py
   - backend/tests/test_tinvest_streams.py
   - docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md

3. Tests added/changed:
   - transport: single subscribe request (account + pingDelayMs), Bearer
     authentication header, `rpcStatus` -> `BrokerConnectionError`.
   - streams: `orderState.trades[]` -> `TradeFill`; a duplicate `tradeId` across
     two `order_state` messages applied exactly once; manager dispatch via
     `order_state` only (two frames -> PARTIALLY_FILLED -> FILLED); statuses
     NEW/PARTIALLYFILL/FILL/REJECTED/CANCELLED retained. Tests/assumptions that
     required the simultaneous TradesStream were removed.

4. pytest result (on master `8529bc0`): `235 passed, 1 skipped` (the 1 skip is the
   opt-in live sandbox integration test, skipped because no credentials). The
   current `agent/control` working tree is the older baseline and reports
   `197 passed`.

5. ruff result: `All checks passed!` (app + tests).

6. npm build result: `✓ built` successfully (vite).

7. Commit SHA: `8529bc0` (branch `master`).

8. Remaining limitation / uncertainty:
   - The live WebSocket operation-selection/channel semantics were not verified
     against a real sandbox (no credentials/network available). This is recorded
     in TASK-09 §23/§24.
   - Branch divergence: this report was produced while the working tree was on
     `agent/control` (`509a019`, based on `54e5b96`) rather than the product
     `master`. The product change lives on `master` (`8529bc0`) and was not
     re-applied or merged here.

9. Confirm push was NOT performed: correct — no push was run for this task.

## CHATGPT REVIEW
This section is reserved for ChatGPT. OpenCode must not modify it.
