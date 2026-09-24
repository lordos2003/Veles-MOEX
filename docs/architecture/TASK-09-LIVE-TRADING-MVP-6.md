# Veles-MOEX — Task 09: Live Trading / Trading Engine (MVP-6)

## Status

Architecture specification prepared after verification against the current Veles Help Center and current T-Invest API documentation.

This document defines the scope for MVP-6. It is a specification for implementation; it does not authorize autonomous changes to trading logic or financial parameters.

## 1. Goal

Implement the first live-trading execution layer for Veles-MOEX.

The system must be able to take signals and execution decisions produced by the already implemented Strategy Engine, DCA/Grid MVP-4 and Full Exit Engine MVP-5, validate them through Risk Manager, and execute them through the broker abstraction.

The MVP broker remains **T-Invest**.

**T-Invest Open API and T-Invest MCP are two alternative transports of the same broker integration, not separate brokers.**

## 2. Existing components that must be reused

MVP-6 must reuse the existing domain logic from:

- Strategy Engine MVP-2
- Backtest Engine MVP-3
- DCA/Grid MVP-4
- Full Exit Engine MVP-5
- BrokerAdapter and broker-neutral DTOs

Do not duplicate strategy, DCA, grid or exit calculations inside the live execution layer.

The live engine is responsible for orchestration and execution state, not for inventing another trading model.

## 3. Target architecture

```
Strategy Engine
      |
      v
Trading Engine
      |
      +----> DCA / Grid
      |
      +----> Exit Engine
      |
      v
Risk Manager
      |
      v
Order Manager <----> Position Manager
      |
      v
BrokerAdapter
      |
      +-----------------------------+
      |                             |
 T-Invest Open API             T-Invest MCP
```

The Strategy Engine, DCA/Grid, Exit Engine, Trading Engine, Order Manager, Position Manager and Risk Manager must not depend on the selected T-Invest transport.

The broker integration layer exposes the same broker-neutral DTOs and lifecycle semantics for both transports.

## 4. BrokerAdapter contract

The live execution layer requires broker-neutral operations for at least:

- account retrieval;
- instrument information;
- current positions;
- active orders;
- place market order;
- place limit order;
- cancel order;
- order status;
- fills/deals;
- portfolio/balance information;
- trading status;
- price/instrument constraints needed before order submission.

The adapter must expose a stable internal contract.

T-Invest-specific protocol objects must not escape the adapter.

### T-Invest Open API

The current T-Invest API provides:

- PostOrder;
- PostOrderAsync;
- CancelOrder;
- GetOrderState;
- GetOrders;
- ReplaceOrder;
- GetMaxLots;
- GetOrderPrice;
- OrderStateStream;
- TradesStream;
- PositionsStream;
- PortfolioStream.

The API supports an idempotency key for orders. The order-state stream exposes partial execution events.

### T-Invest MCP

T-Invest MCP is the alternative transport for the same T-Invest broker.

The official T-Invest MCP endpoint is:

`https://invest-public-api.tbank.ru/mcp`

It uses Streamable HTTP and Bearer authentication.

The official T-Invest MCP documentation confirms trading capabilities including market/limit orders, stop orders and cancellation.

The implementation must treat MCP as a transport adapter, not as a separate broker or trading engine.

Because MCP tool schemas are protocol/tool-layer details, they must be translated inside `TInvestMcpAdapter` into the same broker-neutral DTOs used by `TInvestAdapter`.

## 5. Order lifecycle

The internal order lifecycle must explicitly distinguish:

- intent created;
- submitted;
- accepted/working;
- partially filled;
- filled;
- cancellation requested;
- cancelled;
- rejected;
- failed/unknown.

The exact broker status values must be mapped into these internal states.

A partially filled order must remain a live order until its remaining quantity is either filled or cancelled.

The system must never treat a partial fill as a complete fill.

## 6. Idempotency and duplicate protection

Every live order submission must have an internal execution identity and an idempotency key.

The system must prevent duplicate submission when:

- a network timeout occurs after submission;
- the broker response is lost;
- the process reconnects;
- an event is delivered more than once;
- the same execution decision is retried.

For T-Invest Open API, use the broker-supported order request/idempotency identifier.

The internal order record must retain the relationship:

```
strategy/bot execution
        |
execution intent
        |
internal order
        |
broker request/idempotency id
        |
broker order id
```

## 7. Order synchronization

Live state cannot rely only on local events.

On startup and after reconnect:

1. load local open execution state;
2. query broker active orders;
3. query broker positions;
4. reconcile local and broker state;
5. subscribe to live order/trade/position streams;
6. resume execution only after reconciliation succeeds.

T-Invest provides OrderStateStream for order state, TradesStream for executions, PositionsStream for position changes and PortfolioStream for portfolio updates.

The system must tolerate duplicate and out-of-order external events.

## 8. Position Manager

Position Manager is the authoritative local representation of the broker position after reconciliation.

It must maintain:

- instrument;
- signed quantity;
- average price;
- current price when available;
- realized P&L;
- unrealized P&L where supplied/calculable;
- fees where supplied;
- last synchronization timestamp.

Position changes must be driven by actual broker fills/position updates, not merely by the fact that an order was submitted.

After DCA fills, the new average price must feed the existing DCA/Grid and Exit logic.

## 9. Order Manager

Order Manager is responsible for:

- translating execution intents into broker orders;
- validating broker-level order constraints;
- submission;
- cancellation;
- status tracking;
- fill tracking;
- retry/reconciliation;
- idempotency;
- mapping broker errors to internal error categories.

Order Manager must not decide whether a strategy should enter or exit.

That decision belongs to Strategy/Trading/Exit logic.

## 10. Risk Manager

MVP-6 Risk Manager is an execution gate.

Before every live order it must be possible to verify at minimum:

- bot is running;
- instrument is allowed;
- trading session/instrument status permits trading;
- order quantity is positive and valid;
- price is valid for the instrument;
- required funds/position capacity are available;
- the order does not violate configured execution limits;
- emergency stop is not active.

Risk Manager must not autonomously tune strategy parameters.

MVP-6 must not introduce an investment optimization algorithm.

### 10.1. Execution preconditions implemented (MVP-6.6)

`RiskManager.check_order()` is the authoritative gate before every live order
and enforces, in order:

1. emergency stop is not active;
2. quantity is positive;
3. LIMIT intents carry a valid positive limit price (MARKET intents do not
   require one);
4. instrument is allowed: not in the configured `blocked_instruments` set, and
   the optional broker-neutral `instrument_status_check` dependency (if wired)
   does not report trading as not permitted;
5. configured position limit is not exceeded (worst-case projected position);
6. configured daily loss limit is not breached.

The **bot RUNNING state is NOT checked here**: the bot lifecycle (MVP-6.5)
remains the upstream lifecycle gate and is not duplicated inside the Risk
Manager.

**Configuration source:** the RiskManager limits are supplied from the typed
application settings (`risk_max_position_size`, `risk_daily_loss_limit`,
`risk_max_concurrent_bots`, `risk_blocked_instruments` environment variables),
mapped by `risk_limits_from_settings()` in `app.trading.live_execution`.
Unset values keep the corresponding check disabled; no financial defaults are
invented. The configuration is separate from strategy parameters.

**Explicitly unavailable boundaries (not fabricated):**

- *Instrument trading-session status:* the broker-neutral
  `instrument_status_check` dependency is defined and tested, but NOT wired in
  production: instrument trading status is stored in PostgreSQL behind the
  async `InstrumentService`, while the execution gate is synchronous. Wiring it
  requires an async-aware lookup (a follow-up task). No hardcoded MOEX session
  rules.
- *Funds/position capacity:* broker account facts (`available_cash`, `equity`)
  are exposed only through async `BrokerAdapter` calls; the synchronous gate
  cannot consume them without a larger architectural change. The check is
  explicitly unavailable and no fake balances are used.

## 11. Bot lifecycle

The bot lifecycle must support:

- START;
- RUNNING;
- STOP_REQUESTED;
- STOPPED;
- ERROR;
- EMERGENCY_STOP.

Normal Stop follows Veles semantics: the bot stops initiating further activity while an active trade can be allowed to complete according to the configured behavior.

Emergency Stop is different: it is an explicit cancellation of the bot's active execution management. Active bot orders are cancelled where possible and the remaining broker position is left outside active bot management for manual control.

Veles documents this distinction between normal stop and urgent stop.

### MVP-6 live integration boundary

The MVP-6 live runtime wires the execution path as:

`LiveExecutionService.submit()` -> `BotRuntime.submit_intent()` ->
`TradingEngine.submit_intent()` -> `RiskManager.check_order()` ->
`OrderManager.submit()` -> broker.

In this MVP the live runtime wires:

- The **bot lifecycle** as the upstream control layer (`BotRuntime` /
  `BotRuntimeManager`); a bot must be RUNNING before its intents are accepted.
  START transitions run through `RiskManager.check_start()` before RUNNING and
  `start_bot()` on success.
- `RiskManager.check_order()` is the authoritative execution gate (emergency
  stop, position-size, daily-loss where data is available) and is called before
  every live order.

Bot lifecycle semantics (correction #1):

- **Normal STOP ordering**: RUNNING -> STOP_REQUESTED -> cancel active bot
  orders -> `RiskManager.stop_bot()` -> STOPPED. The `max_concurrent_bots` slot
  stays occupied while cancellation is in progress. Normal STOP does not close
  the position. If cancellation fails, the bot transitions to ERROR and the
  slot is released only after that transition.
- **EMERGENCY_STOP**: blocks new intents, cancels active bot orders through the
  broker-neutral `OrderManager`, and always releases the Risk Manager slot on
  completion; the position is never closed automatically.
- **Restart semantics** (persisted state vs runtime): at live-service startup,
  persisted bot states are restored into the `BotRuntimeManager` from the
  existing `BotRepository`. Persisted RUNNING/STARTING bots are restored in
  ERROR (execution blocked until an explicit START); persisted STOP_REQUESTED is
  restored as STOPPED; other states are restored as-is. The Risk Manager is
  never re-occupied via `start_bot()` after a process restart, and the DB is
  synced to the restored state, so DB and runtime cannot contradict on
  executability.
- **START rejection persistence**: if the Risk Manager rejects a START, the
  persisted bot state is synced to the actual lifecycle state (ERROR) and the
  API returns an explicit error; the DB is never left in RUNNING or stale
  STOPPED.
- **API error mapping** (mutating endpoints): bot not found -> 404; live
  runtime unavailable -> 503; invalid lifecycle transition / risk-manager START
  rejection -> 409; lifecycle execution failure -> 503. Mutations are rejected
  when no real application `BotRuntimeManager` is wired (no fallback runtime).

Remaining boundaries (kept in sync with the implementation, not
production-integrated):

- The `TradingEngine.process()` (Strategy -> TradingEngine) path is **not**
  wired into the live runtime: no live `StrategyEngine`/`StrategyConfig`
  composition exists in MVP-6, so `process()` is an integration seam (it raises
  if invoked without an engine/config).
- There is **no production risk-limits configuration source**; `build_live_service()`
  uses default empty `RiskLimits()` (no invented financial defaults).
- Per-bot order correlation relies on `bot_id` on intents/orders; EMERGENCY_STOP
  cancels a bot's active orders only through the existing broker-neutral
  `OrderManager.cancel()` path when an `OrderManager` is wired.

## 12. Recovery

After application restart or connection loss:

- do not blindly recreate the grid;
- do not blindly submit the last execution intent;
- first reconcile broker state;
- identify already-filled, active, cancelled and unknown orders;
- restore the bot execution state from broker facts plus durable local state;
- only then continue.

If broker state cannot be reconciled safely, the bot must enter ERROR and stop new order submission.

## 13. Veles-compatible behavior

The following Veles behavior is relevant to MVP-6:

- the bot continuously monitors the market and executes strategy-driven entries, averaging and exits;
- active trades have explicit execution state;
- partial/awaiting grid orders are distinct from active broker orders;
- partial grid orders may be placed progressively as earlier orders execute;
- if bot orders are externally deleted or modified, Veles treats this as an execution-management problem and can stop the bot with an error;
- normal Stop and urgent Stop are different operations;
- an existing exchange position can, in Veles, be brought under bot management.

For MOEX/T-Invest, equivalent behavior must be implemented using T-Invest account, order and position semantics rather than copying exchange-specific futures concepts that do not apply.

## 14. MOEX/T-Invest order constraints

Before submission the system must use instrument metadata supplied by T-Invest.

Relevant data includes:

- instrument UID;
- lot size;
- minimum price increment;
- currency;
- trading status;
- availability through T-Invest API.

Prices and quantities must be normalized to broker/instrument constraints before submission.

Do not assume crypto/futures-specific tick, contract or position rules from the separate Bybit research project.

## 15. Market-data dependency

MVP-6 needs a live market-data source for strategy evaluation.

The market-data layer must remain broker-neutral.

For T-Invest this may use the existing T-Invest market-data capabilities, including streaming candles and current prices.

The execution engine must not directly depend on T-Invest market-data message types.

## 16. Persistence

Live execution state must be durable.

At minimum persist:

- bot status;
- active trade/execution state;
- execution intents;
- internal orders;
- broker order identifiers;
- idempotency identifiers;
- fills/deals;
- reconciliation state;
- timestamps;
- terminal error state.

A process restart must not require reconstructing active execution state from memory.

## 17. Error handling

Broker errors must be classified at the adapter boundary, for example:

- validation/rejected;
- insufficient funds;
- trading unavailable;
- instrument unavailable;
- rate limited;
- authentication/authorization;
- transport/network;
- broker temporary failure;
- unknown state.

Only errors that are safe to retry may be retried automatically.

Unknown submission outcome must trigger reconciliation rather than blind retry.

## 18. MCP-specific execution rule

MCP is an alternative transport, but its protocol is tool-oriented rather than exposing the same gRPC method surface directly.

Therefore:

```
Trading Engine
      |
 BrokerAdapter
      |
 +----+--------------------+
 |                         |
TInvestAdapter        TInvestMcpAdapter
 |                         |
Open API              T-Invest MCP
```

No MCP tool names, confirmation mechanics or MCP-specific request objects may leak into Trading Engine, Order Manager or Risk Manager.

The adapter must provide the same semantic contract.

## 19. Explicit non-goals for MVP-6

Do not implement in this task:

- additional brokers;
- direct MOEX ASTS/FIX/TWIME;
- autonomous strategy optimization;
- parameter tuning;
- portfolio optimization;
- trailing exits;
- new strategy indicators;
- new DCA/Grid modes;
- new exit modes;
- high-frequency execution;
- tick-level backtesting;
- partial-fill simulation changes in Backtest Engine unless required solely to share interfaces;
- a separate microservice architecture.

## 20. Required validation

Implementation must include tests for:

1. market order lifecycle;
2. limit order lifecycle;
3. partial fill;
4. full fill after partial fill;
5. cancellation;
6. rejection;
7. idempotent retry;
8. lost response followed by reconciliation;
9. duplicate broker events;
10. restart/recovery;
11. position update after fill;
12. DCA average-price update after live fill;
13. TP recreation after DCA;
14. emergency stop;
15. normal stop;
16. risk rejection;
17. instrument price/quantity normalization;
18. Open API adapter mapping;
19. MCP adapter mapping;
20. identical broker-neutral semantics for both T-Invest transports.

No real-money integration test may submit an order unless the test explicitly uses a safe T-Invest sandbox/test environment.

## 21. Implementation boundary

MVP-6 should first implement the broker-neutral live execution domain and interfaces, then T-Invest Open API execution, then T-Invest MCP transport mapping.

The existing Strategy/DCA/Grid/Exit behavior is considered input to this task and must not be redesigned.

MVP-6.6 completed the execution-side Risk Manager preconditions (positive
quantity, valid LIMIT price, instrument/trading permission via the configured
`blocked_instruments` set and the broker-neutral `instrument_status_check`
dependency, configured position/daily-loss limits, emergency stop) with the
limits supplied from the typed application settings (`risk_*` environment
variables). The instrument trading-session status and the funds/capacity
checks are explicitly unavailable in the current architecture (documented in
section 10.1); no fabricated values are used.

## 22. Reference sources

Veles:
- Veles bot overview and execution model.
- Veles bot lifecycle and active trade behavior.
- Veles DCA/grid partial placement and pull-up behavior.
- Veles normal and urgent stop behavior.

T-Invest:
- Orders service and order lifecycle.
- OrderStateStream.
- TradesStream.
- PositionsStream.
- PortfolioStream.
- instrument trading status and instrument constraints.
- official T-Invest MCP documentation.

## 23. Implemented scope — MVP-6.2 (T-Invest Open API execution)

This section records what is actually implemented for real order execution
through T-Invest Open API. It is additive to the broker-neutral live execution
domain (MVP-6.1). Things that are not yet implemented must not be treated as
done.

### Canonical quantity unit

- The canonical quantity unit inside Veles-MOEX is **instrument units**
  (pieces/shares). `Position.quantity`, `Fill.quantity`,
  `ExecutionIntent.quantity` and `BrokerOrderRequest.quantity` are units.
- T-Invest `PostOrder.quantity` accepts **lots**.
- Conversion `units / lot_size -> lots` happens **only inside `TInvestAdapter`**
  using the instrument `lot_size`. Units that are not an exact multiple of the
  lot size are rejected **before** any broker call (raises an invalid-request
  error). No float is used; all computation is `Decimal`.
- `BrokerOrder.requested_quantity` / `executed_quantity` remain in the broker's
  native unit (lots) as a read-only snapshot; live fill/position accounting uses
  units via fills/position events.

### Decimal and price

- All money/price/quantity values are `Decimal`. `BrokerOrderRequest.quantity`
  is `Decimal` and `BrokerOrderRequest.price` is `Decimal | None`.
- `Decimal <-> Quotation` conversion happens at the adapter boundary; domain
  never sees `Quotation`.
- For shares/ETF a currency price representation is used. The price is validated
  against `tick_size` / `min_price_increment` (the price must be a multiple of
  the tick); an invalid price is rejected before submission.
- `BESTPRICE` is **not** silently downgraded to `LIMIT`: it is unsupported in
  MVP-6.2 and surfaces as an unknown/unsupported type.

### Account context

- Execution requires an explicit `account_id`. `BrokerOrderRequest.account_id`
  must be set; `cancel_order` and `get_order` take `account_id` explicitly and
  reject `None`.
- `_first_account_id()` is not used for live order operations; it remains only
  for read-only endpoints. `order_id_type` (`ORDER_ID_TYPE_EXCHANGE`) is passed
  on the broker boundary.

### Idempotency

- One execution intent = one UUID idempotency key. The key is created once and
  stored on the internal order; the same key is reused on retry and is never
  regenerated for the same order.
- A missing key is generated as UUID4; a supplied non-UUID key is rejected (the
  broker would otherwise substitute a generated id and correlation would be
  lost). The key is sent as `PostOrder.order_id` and echoed back as
  `order_request_id`.

### Order lifecycle

- `NEW -> SUBMITTED/WORKING`, `PARTIALLYFILL -> PARTIALLY_FILLED`,
  `FILL -> FILLED`, `REJECTED -> REJECTED`, `CANCELLED -> CANCELLED`.
- `UNSPECIFIED` / unknown status maps to `UNKNOWN`, never to `FAILED`.
- `PARTIALLY_FILLED` stays a live order while a positive quantity remains.
- T-Invest stream behaviour (a partially filled order may stay
  `PARTIALLY_FILLED` instead of returning to `CANCELLED`) is accommodated without
  weakening the domain transition rules.

### Fills and position accounting

- The authoritative source of fills is the individual executions from
  `TradesStream` and `OrderStateStream.trades` (each `trade_id`, price,
  quantity in units, timestamp) -> broker-neutral `TradeFill`.
- `lots_executed` is used for status/reconciliation, not to fabricate fills.
- Live fill accounting no longer depends on `GetDeals`/operations
  (`_sync_broker_fills` was removed). Operations/GetDeals remain an audit source
  only.
- **Deduplication**: the same execution may arrive via both `TradesStream` and
  `OrderStateStream.trades`; it is applied once by `trade_id` (`fill_id`), so the
  position changes exactly once regardless of arrival order.

### Stream manager and recovery

- `TInvestStreamManager` subscribes to the order/trade streams for one account,
  dispatches broker-neutral events into the `OrderManager`, and performs
  exponential-backoff reconnect.
- After a (re)connect it reconciles via unary `GetOrders` / `GetOrderState` /
  `GetPositions` (order status and position state) before resuming streaming.
- The wire/stream transport is abstracted behind `TInvestStreamTransport`.
  Process-restart durable recovery is out of scope for MVP-6.2.

### Scope and sandbox limitations

- MVP-6.2 covers **shares and ETF** (currency price representation).
  Bonds (`PRICE_TYPE_POINT` + accrued interest) and futures (points, GO) are not
  supported.
- Sandbox is configurable (`tinvest_sandbox`). Lifecycle integration is covered
  deterministically with a mocked client. Realistic multi-step partial fills
  cannot be produced by the sandbox, so partial-fill and idempotency behaviour is
  covered by deterministic unit tests / a fake client.

## 24. Real Open API transport — MVP-6.2.1

This section records the *real* T-Invest Open API transport wired into the
broker-neutral execution boundary. It reports factual implementation status and
does not claim live verification that was not performed.

### Unary calls (real REST gateway)

The existing `TInvestAdapter` issues real HTTP calls through `TInvestClient`
(httpx) to the REST gateway, using the documented service paths:

- `OrdersService/PostOrder` (`place_order`)
- `OrdersService/CancelOrder` (`cancel_order`)
- `OrdersService/GetOrderState` (`get_order`)
- `OrdersService/GetOrders` (`get_orders`)
- `OperationsService/GetPortfolio` (`get_open_positions`, used for reconciliation;
  it carries the average price required by the Position Manager)

Request bodies use the real API JSON names (`accountId`, `instrumentId`,
`quantity` in lots, `direction`, `orderType`, `orderId` = UUID idempotency key,
`price` as `Quotation` for LIMIT). Domain quantity stays in units; the adapter
converts `units / lot_size -> integer lots` and validates lot/tick constraints.

### Streams (real JSON WebSocket)

The official T-Invest WebSocket service exposes the gRPC streaming methods over
JSON: `wss://invest-public-api.tbank.ru/ws/` (sandbox host alias resolvable via
config). The concrete `TInvestWebSocketStreamTransport` implements the existing
`TInvestStreamTransport` boundary:

1. opens the WebSocket connection with `Authorization: Bearer <token>` and the
   `Web-Socket-Protocol: json-proto` header;
2. subscribes to `OrderStateStream` and `TradesStream` by sending the documented
   requests (`{"accounts": [...], "pingDelayMs": ...}`);
3. reads JSON frames (server `ping` frames count as keep-alive);
4. normalizes the real camelCase field names (`orderState`,
   `executionReportStatus`, `tradeId`, `dateTime`, `lotsRequested`, ...) to the
   broker-neutral snake_case shape;
5. yields normalized dicts to the existing `TInvestStreamManager`, which decodes
   them into `OrderUpdate` / `TradeFill` and hands them to the `OrderManager`.

If no frame is received within a configured timeout the connection is considered
dead and an error is raised so the manager's exponential-backoff reconnect kicks
in. After reconnect the manager performs unary recovery (`GetOrders`,
`GetOrderState`-ish via order refresh, `GetOpenPositions`).

### Authentication

The token is read from configuration/environment (`VELES_TINVEST_TOKEN`), never
from source. The WebSocket endpoint and the sandbox REST/WS hosts are selected by
configuration (`tinvest_sandbox`, `tinvest_base_url`, `tinvest_stream_url`),
not hardcoded.

### Integration-test status

- A live sandbox integration test is opt-in via the `integration` marker and is
  **skipped** when no sandbox token is configured. It does not fake a pass.
- As of this writing no T-Invest credentials/network token are available in the
  environment, so the live sandbox verification was **not performed**. All
  behaviour is covered by deterministic tests backed by the official documented
  request/response contract (camelCase JSON fields) and a fake WebSocket source.

### Verified quality gates

- No T-Invest imports in `app/trading` (only broker-neutral `app.brokers.base`);
- no `float` in the execution path (`Decimal` only, including `units <-> lots`
  and Decimal `-> Quotation`);
- `BESTPRICE` is not downgraded to `LIMIT`;
- `_first_account_id()` is not used for live order operations;
- one `trade_id` is applied exactly once (deduplication across repeated
  `OrderStateStream` messages).

### Stream choice — OrderStateStream only

> Для live execution MVP-6.2 используется T-Invest **OrderStateStream**.
> Individual executions берутся из `orderState.trades[]`. **TradesStream не
> используется**, поскольку T-Bank Dev Portal помечает его deprecated, а
> OrderStateStream уже содержит необходимые execution events.

This removes the need for an unconfirmed multiplexing of two stream operations
on one WebSocket connection: the transport opens one connection and sends a
single OrderStateStream subscription request (`{"accounts": [...],
"pingDelayMs": ...}`). Executions come from `orderState.trades[]`. It is not
claimed that TradesStream is technically impossible to use — it is simply not
used, and the single OrderStateStream subscription is the documented,
non-deprecated live source for order states and executions.



