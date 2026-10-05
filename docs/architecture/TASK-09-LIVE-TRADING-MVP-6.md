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

**MVP-6.12 owner contract D7 (position-reducing exemption, 2026-09-30):** a
**reducing** intent — the Deal closing take-profit, or any order that reduces
the current live position — is **exempt** from checks 5–6 (position limit,
daily loss limit): when the PositionManager position for the intent's FIGI is
non-zero, the intent side is opposite to the position sign, and the quantity
does not exceed the position magnitude, the order is a *reduction* and must
never be blocked by a limit meant to stop risk from growing. Checks 1–4
(emergency stop, quantity, price, instrument permission) still apply to
reducing intents. An intent that increases the position (or a reduction with
quantity beyond the position) keeps the full MVP-6.6 behavior; without a known
position the exemption does not apply.

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

## 25. Strategy live integration — MVP-6.7

The Strategy Engine is now production-wired into the live Bot Runtime and
Trading Engine:

```
Bot (strategy_version_id)
  -> StrategyVersion (immutable JSONB config)
     -> StrategyConfig (validated, per bot)
        -> StrategyEngine.evaluate(MarketContext) -> Plan
           -> BotRuntime.execute_strategy()
              -> TradingEngine.process() (per-bot engine)
                 -> plan_to_intents() (orchestration boundary)
                    -> RiskManager.check_order()
                       -> OrderManager.submit() -> BrokerAdapter
```

### StrategyVersion loading

`app/bots/strategy.py` is the minimum repository/service boundary: a Bot's
referenced `StrategyVersion` is loaded and its JSONB configuration validated
through the existing `StrategyConfig` model. `StrategyVersion` is never
mutated. A missing version or an invalid configuration raises
`StrategyLoadError`, which blocks execution explicitly (the bot stays in ERROR;
the API reports an explicit 409 start failure).

### Per-bot strategy composition

Each bot runtime loads **its own** immutable `StrategyConfig` on START and
composes its own `TradingEngine` (shared broker-neutral `StrategyEngine`
instances via `compose_strategy_engine()`, per-bot `StrategyConfig`). There is
no global strategy configuration. The bot cannot enter RUNNING unless the
strategy loads and validates; a failed load never occupies a RiskManager
concurrent-bot slot. MVP-6.5 restart semantics are unchanged.

### ExecutionIntent conversion boundaries (`app/trading/plan_intent.py`)

Only plan items with safe, real domain values become live intents:

- **DCA/Grid orders** (`GridOrder`): converted (real quantity/price); intent
  ids are deterministic content hashes, preserving `ExecutionIntent`
  idempotency (repeated identical plans deduplicate in the OrderManager).
- **Entry signals** (`EntrySignal`): NOT converted — the domain carries no
  order quantity (explicit boundary; no fabricated quantity).
- **Exit plans** (`ExitPlan`): NOT converted — the quantity originates from the
  `position_qty=1.0` placeholder in `StrategyEngine.evaluate()` (explicit
  boundary; a live exit quantity must come from real position state).

### MarketContext boundary

`MarketContext` is the broker-neutral input to
`BotRuntime.execute_strategy(context)`; it is always injected explicitly.
There is currently **no production market-data source wired** into the runtime
(no hardcoded prices, no fake candles, no fake positions). Wiring a live
MarketContext source (market data layer) is a follow-up task.

### Risk configuration limitation

`StrategyConfig.risk` is **not** copied into the execution RiskManager; the
production RiskManager uses only the typed application settings (`risk_*`).
Per-bot risk configuration is not yet supported by the RiskManager boundary —
documented limitation, no precedence rules invented.

### Tests

`tests/test_strategy_live_integration.py` covers: strategy version loading
(valid / missing / invalid), failed load -> ERROR without a risk slot, no
strategy execution outside RUNNING, plan -> TradingEngine -> RiskManager ->
OrderManager, risk rejection before the broker, idempotent plan re-evaluation,
entry/exit conversion boundaries, broker-neutrality of the strategy code, and
restart semantics with the strategy path.

## 26. Market context & sizing boundary — MVP-6.8

This section records the MVP-6.8 boundary between live market data, Strategy
Engine evaluation and safe order sizing. It is additive to the MVP-6.6/6.7
work; things that are not wired are reported as explicit boundaries (no
fabricated values).

### Target path

```
Market Data -> MarketContext -> StrategyEngine -> DCA/Grid -> Plan
             -> safe ExecutionIntent -> RiskManager -> OrderManager -> BrokerAdapter
```

### Production MarketContext source

- `app/trading/market_context.py` provides the smallest broker-neutral
  integration: `build_market_context(market_data, instrument_figi)` fetches the
  real last trade price via the existing broker-neutral
  `MarketDataService.get_last_price()` and builds a `MarketContext(price,
  timestamp)`. No T-Invest types leak; `MarketContext.price` is `Decimal ->
  float`, and no hardcoded price, synthetic candle or fake timestamp is used.
- A missing/non-positive live price raises `MarketContextUnavailable`, so live
  strategy execution is blocked rather than built on fabricated data.
- **Documented missing dependency:** the candle/snapshot source (needed by the
  Entry Engine filter evaluation) and the per-bot `timeframe` are not wired. The
  strategy evaluation that requires a live `Snapshot` remains blocked until a
  candle/timeframe source is configured. This boundary supplies a real last
  price and its timestamp only.

### Position-sizing source

- `app/trading/sizing.py` defines the typed broker-neutral boundary:
  `PositionSizing(base_nominal)` and `SizingNotConfigured`.
  `PositionSizing.resolve_base_nominal()` returns the positive base nominal or
  raises `SizingNotConfigured`.
- There is **no authoritative sizing source** in the Bot/trading configuration,
  so the production per-bot `TradingEngine` is created without a sizing source
  and `TradingEngine.process()` raises `SizingNotConfigured` until a sizing
  source is configured. **No financial default is invented** (the
  `Decimal("100")` engine default and `1.0`/`100` placeholders are never used
  as live values).

### Strategy -> DCA/Grid

- `StrategyEngine.evaluate(config, context, *, base_nominal=None)` now builds
  the DCA/Grid plan items through the existing `DCAGridEngine` only when an
  explicit live sizing source (`base_nominal`) is supplied and the entry signal
  fires; `Plan.grid` is populated from the grid state's eligible orders. The
  `Decimal("100")` default is never relied upon by the live path.
- When `base_nominal` is `None` the engine keeps its previous behaviour (no
  grid items), so Backtest and the existing strategy tests are unchanged.

### Entry intent / boundaries

- A live **entry intent** is created only when all fields are real and valid:
  `bot_id`, `instrument`, `side`, positive quantity, MARKET or valid LIMIT price
  and a deterministic intent id (content hash) via `plan_to_intents`. The path
  stays `BotRuntime -> TradingEngine -> RiskManager -> OrderManager`.
- **Entry signals** are still not converted (no order quantity in the domain).
- **Exit plans** with the `position_qty=1.0` placeholder remain blocked (no
  live exit conversion) until the Position Manager supplies a real quantity.

### Lifecycle / risk-slot

MVP-6.5 semantics are preserved: a strategy/engine-factory failure (including a
missing sizing source) during START transitions the bot to ERROR and does not
consume the Risk Manager concurrent-bot slot; START rejection remains an
explicit error; STOP and EMERGENCY_STOP are unchanged.

### Broker neutrality

No `app.brokers.tinvest*` import, T-Invest protocol type or T-Invest transport
code is present inside the Strategy Engine, DCA/Grid, sizing domain or Trading
Engine. Market data is acquired through the broker-neutral `MarketDataService`.

### Testing

`tests/test_mvp68_market_context_sizing.py` covers: real MarketContext built
from broker data, market-data unavailability blocking execution, no fabricated
MarketContext outside the boundary module, per-bot sizing source usage, missing
sizing blocking execution, explicit sizing reaching the DCA/Grid engine, the
`100` default never used by the live path, positive real entry intents,
non-positive quantity rejected before the Order Manager, full path remaining
Risk-Manager-gated, exit placeholder remaining blocked (the MVP-6.8 boundary;
replaced by the real position quantity in §27), and sizing failure at START not
consuming a Risk Manager slot.

## 27. Position state & authoritative quantity — MVP-6.9

This section records MVP-6.9: the live-execution quantity boundary from MVP-6.8
is removed. The Position Manager is now the **only** authoritative source of
quantity for live execution; the old `position_qty=1.0` placeholder is gone
from the live path.

### Authoritative quantity source

- `app/trading/position_manager.py` is the single authoritative source:
  `PositionManager.resolve_quantity(instrument_figi, direction) -> Decimal`
  returns a positive position magnitude valid for an exit. It raises
  `PositionUnavailable` (no position for the FIGI) or
  `InvalidPositionQuantity` (zero quantity, or a sign inconsistent with the
  strategy direction). No fabricated/default quantity is ever returned.
- Positions are obtained through the broker-neutral adapter (`BrokerAdapter
  get_open_positions`) during the existing recovery reconciliation
  (`LiveRecoveryCoordinator`), which feeds `PositionManager`. The broker is
  never queried inside StrategyEngine, ExitEngine, BotRuntime or OrderManager.

### Live path

```
T-Invest -> BrokerAdapter -> PositionManager -> real position quantity
        -> Exit/Strategy planning -> ExitPlan -> ExecutionIntent
        -> RiskManager -> OrderManager
```

- `StrategyEngine.evaluate(..., position_qty=None)` builds exit plans only when
  a real, positive `position_qty` is supplied. **The hardcoded
  `position_qty=1.0` is removed from the live path.**
- `TradingEngine.process()` resolves the real exit quantity from the
  PositionManager (per-bot `instrument_figi`) and passes it to `evaluate`; a
  missing/invalid position yields `position_qty=None`, so **no live exit order
  is generated** (no position, zero quantity or sign mismatch => no live exit).
- `plan_to_intents()` now converts exit plans to `ExecutionIntent`s when they
  carry a positive real quantity; non-positive exit quantities are skipped.

### Quantity rules

- No position -> no live exit order.
- `quantity == 0` -> no live order (`InvalidPositionQuantity`).
- Quantity with a sign inconsistent with the strategy direction (e.g. a LONG
  strategy holding a short position) -> no live order.
- No fabricated or default fallback quantity anywhere in the live path.

### Preserved behavior

- DCA/Grid mathematics unchanged (`DCAGridEngine`).
- Backtest semantics unchanged: Backtest calls `evaluate(config, context)`
  without a position quantity (it keeps its own broker position state), so the
  call produces no planned exits there and does not error; the existing
  Backtest/Exit suites are the regression check.
- T-Invest stays read-only; no actual live order submission is added.

### Broker neutrality

No `app.brokers.tinvest*` import or T-Invest protocol type is introduced into
the strategy, Exit, position or trading-engine layers. `Direction` and the
domain position exceptions stay broker-neutral.

### Testing

`tests/test_mvp69_position_state.py` covers: valid real position, missing
position (`PositionUnavailable`), zero quantity and negative/sign-mismatched
quantity (`InvalidPositionQuantity`), real quantity reaching the ExitPlan, real
quantity reaching the ExecutionIntent, no live exit order when the position is
absent, no fallback quantity, and unchanged Backtest / DCA behavior.



## 28. Market snapshot & per-bot timeframe - MVP-6.10

This section records MVP-6.10: the live Strategy path now receives a real
broker-neutral market snapshot (last price + candle history) built with the
timeframe configured by the bot's own strategy. The MVP-6.8
candle/snapshot source and per-bot timeframe boundary is closed. Production
position sizing remains governed by the MVP-6.9 PositionManager boundary.

### MarketSnapshot contract

- `app/domain/marketdata.py` adds the broker-neutral `MarketSnapshot`
  (FIGI, timeframe, timezone-aware UTC timestamp, `Decimal` last price,
  recent `Candle` history) and the domain error `MarketDataUnavailable`.
  Existing domain types (`Candle`, `LastPrice`, `Timeframe`) are reused; no
  parallel representation is introduced.

### MarketDataService

- `MarketDataService.get_snapshot(figi, timeframe, lookback_bars)` assembles
  the snapshot exclusively from real broker data (last trade price + the most
  recent `lookback_bars` candles for the instrument/timeframe; one extra bar
  of width covers the currently forming candle). A missing/non-positive last
  price or an empty candle history raises `MarketDataUnavailable` instead of
  substituting a synthetic value. The Strategy path never sees T-Invest
  types; T-Invest-specific mapping stays inside `TInvestAdapter`.

### Per-bot timeframe

- `StrategyConfig.timeframe: Timeframe | None = None` � the bot's own
  market-data timeframe, part of the immutable StrategyVersion configuration
  (`Bot/StrategyVersion -> timeframe`). **No global runtime timeframe and no
  implicit production default exist:**
  - a missing timeframe fails the live cycle explicitly
    (`TimeframeNotConfigured`);
  - an invalid timeframe fails strategy configuration validation at load
    time (`StrategyLoadError`).
- `StrategyConfig.lookback_bars: int | None = None` (>= 1) is the **explicitly
  configured** number of candle bars the live market snapshot fetches for the
  bot's timeframe. This is a **project-level contract parameter, not a Veles
  indicator/warmup semantic**: the official Veles documentation defines
  flexible indicators through explicit user parameters (period/length,
  timeframe, method, shift) and does **not** define a universal
  warmup/history/lookback rule, so **no lookback is derived from indicator
  periods/shifts, cross operators, or any other Veles semantic** (no formula,
  no `+1`, no period-as-history). **No implicit default exists:**
  - a missing lookback fails the live cycle explicitly
    (`LookbackNotConfigured`);
  - a non-positive value fails strategy configuration validation at load time
    (`StrategyLoadError`).
- Documented limitation: an indicator whose internal warmup needs more bars
  than the explicitly configured `lookback_bars` may evaluate as undefined ->
  condition False -> no signal (the strategy engine's existing
  insufficient-data semantics, unchanged). Establishing an exact per-indicator
  warmup specification is a boundary pending the Veles specification; this
  project does not invent one.

### Live runtime integration

```
Bot/StrategyVersion -> (timeframe, lookback_bars)
  -> MarketDataService.get_snapshot -> MarketSnapshot
  -> build_market_snapshot_context -> MarketContext
  -> BotRuntime.execute_strategy -> StrategyEngine -> DCA/Grid/Exit
  -> TradingEngine -> RiskManager -> OrderManager
```

- `BotRuntime` gains a `market_context_provider`
  (`(BotStrategy) -> Awaitable[MarketContext]`); `execute_strategy()` uses it
  when called without an explicit context. A missing/invalid snapshot fails
  the cycle explicitly (no fabricated market data). A missing per-bot
  timeframe (`TimeframeNotConfigured`) or a missing explicit lookback
  (`LookbackNotConfigured`) also fails the cycle explicitly.
- `TradingEngine.process()` enforces the live invariants for a per-bot engine
  (`instrument_figi` set):
  - a missing per-bot timeframe raises `TimeframeNotConfigured` (the cycle
    fails explicitly);
  - a market context without a non-empty bar series for the bot's timeframe
    blocks **all** live ExecutionIntent creation/submission for the cycle
    (same blocking semantics as the MVP-6.9 position-state gate).
- The MVP-6.9 position-state invariant remains mandatory: the
  PositionManager is still the only authoritative live quantity source and an
  unresolved position state still blocks all live intents.

### Backtest isolation

BacktestBroker/Backtest semantics, DCA/Grid mathematics and Veles
Filter/Signal semantics are unchanged; the backtest keeps its own
`BacktestConfig.timeframe` and broker position state. The live market-data
path (MarketDataService snapshot) is separable from backtest data.

### Testing

`tests/test_mvp610_market_snapshot.py` covers: a valid MarketSnapshot from
broker data, value preservation into the MarketContext, per-bot timeframe
propagation from the strategy configuration and from the bot runtime, the
correct snapshot retrieval request (FIGI/timeframe/window, explicit
`lookback_bars`), that the lookback is **not** inferred from indicator
period/shift (a config with period/shift but no explicit lookback fails with
`LookbackNotConfigured`), non-positive lookback rejection (config validation),
explicit failure on a missing timeframe (boundary and live cycle) and on a
missing explicit lookback (boundary and live cycle), invalid timeframe
rejection (config validation and strategy load), missing/invalid market
snapshots (non-positive price, empty history, unknown instrument, runtime
cycle block, snapshot without the bot-timeframe series, empty series, missing
snapshot), and the preserved
MVP-6.9 position-state invariant (no order without a position; real
quantity with a valid snapshot + position).

## 29. Bot deposit sizing & entry from confirmed flat — MVP-6.11

This section records MVP-6.11 (approved contracts C1–C5, plus the round-1
correction B1 and the round-2 contracts C6–C7, 2026-09-29/30): the
authoritative live sizing source is the **bot deposit**, the MOEX lot
rounding contract is enforced at the entry boundary, and the live position
state is three-valued so a **confirmed flat** position can start a deal while
an unknown/unreconciled state keeps blocking everything. Entry sizing is an
**entry-only** precondition (B1): the deposit is read at each FLAT entry
(C6) and the entry snapshot is trimmed to exactly `lookback_bars` (C7,
GitHub Issue #3 carry-over from MVP-6.10).

### C1. Deposit is a bot setting (Veles "Full list of bot settings")

- The Veles Help Center "Full list of bot settings" lists the bot deposit
  ("The amount within which the bot trades") among the bot-level settings
  (bot name, bot direction, instrument, strategy, timeframe), separate from
  the strategy settings. This MVP follows that: `Bot.deposit` (nullable
  `Numeric(20,8)`, migration `0004_bot_deposit`) is a **bot** field, not a
  `StrategyVersion` field.
- API: `deposit` is exposed in the bot API schema read/write:
  `GET /api/bots/{id}` returns it; `PATCH /api/bots/{id}` sets or clears it.
  Validation is `> 0` and the `deposit` key is **required**
  (`BotDepositUpdate.deposit: Decimal | None = Field(gt=0)`, no default): a
  non-positive value is rejected (422), `None` clears, and a PATCH without
  the deposit key is rejected instead of silently clearing the stored value
  (round-1 review observation 2). No default deposit is invented; an unset
  deposit keeps the existing `SizingNotConfigured` behavior for the live
  cycle.
- Frontend: no bot form exists yet; no UI change was required (build stays
  green).

### C2. Deposit -> base nominal (broker-neutral, one function)

- `app/trading/sizing.py:deposit_to_base_nominal(deposit, dca_grid)` is the
  single broker-neutral conversion; the sum of the nominals of **all** grid
  orders of one deal (first order included) equals the deposit `D`:
  - SIMPLE: `n = dca_grid.levels`, `k = 1 + martingale/100` (`k = 1` when
    martingale is off), `first_nominal = D / sum(k**i, i=0..n-1)`; level
    `i` nominal = `first_nominal * k**i` — the existing `DCAGridEngine`
    martingale math is unchanged, only the base nominal is derived from `D`.
  - CUSTOM: level nominal = `D * nominal_percent / 100` (the existing
    `_build_custom` math with `base_nominal = D`). When the level
    percentages sum to more than 100 the deal would exceed the deposit:
    explicit `CustomDepositExceeded`.
  - SIGNAL: the existing SIGNAL engine does **not** use
    `DCAGridConfig.levels` as a maximum order-count limit (subsequent
    averaging orders are unbounded), so **no limit is invented**: live SIGNAL
    sizing blocks with an explicit `SignalSizingUnsupported` (documented gap,
    pending a separately approved contract).
- Spot semantics only: the deposit is used 1:1; there is no
  leverage/margin field in the configuration and none is added (the Veles
  bot-settings list contains no such field). No FX conversion: the deposit
  currency is the instrument's trading/price currency.
- `PositionSizing` now carries the deposit (plus the instrument lot size and
  currency) and `resolve_base_nominal(dca_grid)` applies C2; the
  MVP-6.8 `base_nominal` path is unchanged and the `SizingNotConfigured`
  semantics are unchanged (unset/non-positive deposit -> the same error).
- **Entry-only (round-1 correction B1):** `resolve_base_nominal` is consulted
  on the FLAT live entry path only. An `OPEN` live position never reads the
  deposit or the grid mode: the exits of an open deal depend only on the
  PositionManager quantity, so an open deal keeps its exit maintenance even
  when the deposit is unset/cleared or the grid mode is SIGNAL /
  CUSTOM-over-100% (those modes block **entries**, never **exits**). The
  generic (no live position state) engine path is unchanged.
- Known boundary: the Backtest path sizes orders from its own `BacktestConfig`
  and does not use the bot deposit; the Veles backtest sizing semantics are
  not defined in the documentation inspected, so no backtest deposit rule is
  invented (documented in the MVP-6.11 REPORT).

### C3. MOEX lot rounding (project contract, not a Veles rule)

- `app/trading/sizing.py:round_grid_to_lot(grid, lot_size, currency)` rounds
  each grid level quantity (units = nominal / order_price) **down** to a
  whole number of lots (`lot_size` from the instrument). If **any** order of
  the deal rounds to 0 lots, the **whole entry** is blocked with
  `SizingBelowLot` naming the level, its nominal, price and lot size; no
  partial grid is submitted and the remainder of the deposit after rounding
  stays unused (no redistribution).
- A missing/non-positive `lot_size` or an unresolvable instrument currency
  blocks the entry explicitly (`LotSizeUnavailable` / `CurrencyUnavailable`);
  no default lot or currency is substituted.
- `GridOrder` carries the planned `nominal` (a data carrier added to
  `app/strategies/domain.py`); no DCA/Grid mathematics changed.
- The rounding is applied in `TradingEngine.process()` on the live FLAT
  entry path only; Backtest and the DCA engine math are untouched.

### C4. Confirmed-flat entry (three-valued position state)

- `app/trading/position_manager.py:LivePositionState` — `UNKNOWN`, `FLAT`,
  `OPEN`, plus `SIGN_MISMATCH` — with the gating contract:
  | State | Meaning | Live intents |
  |---|---|---|
  | `UNKNOWN` | never reconciled, reconciliation failed, or stale | none (MVP-6.9 behavior preserved) |
  | `FLAT` | latest **successful** reconciliation confirmed zero/no position | entry only — no exit intents; no re-entry while the bot has active (non-terminal) orders |
  | `OPEN` | reconciled non-zero position, sign matching the direction | exits only (unchanged MVP-6.9); no new grid/entry intents from a fresh evaluation |
  | sign mismatch | reconciled position with the opposite sign | none |
- The state is established **only** by a successful broker position
  reconciliation: `LiveRecoveryCoordinator.recover()` calls
  `PositionManager.mark_reconciled()` after applying
  `BrokerAdapter.get_open_positions` facts (stale local positions are dropped
  first) and `invalidate_reconciliation()` when that call fails. Restored
  (durable) positions from a snapshot are **not** a reconciliation
  (`load_state` resets the state to UNKNOWN); fill-driven position changes
  keep the state updated afterwards (Architecture & Product Specification
  section 8: positions change only from actual fills/updates).
- Entry precondition (FLAT): the bot must have **no active (non-terminal)
  orders** in the OrderManager (correlated by `bot_id`); otherwise the entry
  is blocked for the cycle (a working limit first order / grid is not
  duplicated on the next cycle). When the bot cannot be correlated (no
  `bot_id`) the entry is blocked (the precondition cannot be verified; no
  fabricated safety assumption).
- `TradingEngine` gains `bot_id` for the correlation; the `process()` gating
  follows the table above. The MVP-6.9 invariants are preserved: the
  PositionManager remains the only authoritative live quantity source and an
  unknown/unresolved state still blocks all live intents.
- Documented boundaries (out of scope, separate MVPs): cross-cycle deal
  continuation / grid state persistence (an OPEN position does not resume a
  partially built grid), and the periodic live-cycle scheduler.

### C5. Production wiring

- `build_live_service()` per-bot engine factory wires a broker-neutral async
  `deposit_provider` (reads `Bot.deposit` from the repository at each call),
  `PositionSizing(lot_size=Instrument.lot_size, currency=Instrument.currency)`
  and `bot_id` into the per-bot `TradingEngine`. The engine does **not**
  snapshot the deposit at build time: the value is read at each FLAT entry
  (C6). `Bot.deposit: None` keeps the MVP-6.8 behavior (`SizingNotConfigured`
  on the live cycle; START failure does not consume a RiskManager slot).
  T-Invest stays read-only: this MVP changes no `place_order`/transport code
  and enables no live order submission.

### B1 (round-1 correction). Entry sizing is an entry-only precondition

- Round-1 review rejection: `TradingEngine.process()` resolved the C2 base
  nominal **before** the live position state, so an OPEN position with a
  missing/unset deposit (or a SIGNAL / CUSTOM-over-100% grid mode) aborted
  the cycle and the open deal lost its exit maintenance.
- Correction: `process()` resolves the C2 base nominal via
  `_entry_base_nominal(position_state)` — `None` for OPEN / UNKNOWN /
  SIGN_MISMATCH, resolved only on FLAT (and for a generic engine without a
  live position state). The exit quantity still comes exclusively from
  `PositionManager.resolve_quantity`; no exit depends on any sizing source.
- Regression coverage: OPEN + deposit unset, OPEN + SIGNAL mode, OPEN +
  CUSTOM-over-100% → exit submitted (no grid); FLAT + deposit unset →
  `SizingNotConfigured`, nothing placed.

### C6 (round-2). Deposit edits apply from the next deal

- The `TradingEngine` accepts an optional async `deposit_provider`
  (`Callable[[], Awaitable[Decimal | None]]`). On the FLAT entry path the
  engine calls it at the moment of the entry and resolves C2 with the current
  value; a deposit edit therefore applies from the next deal **without a bot
  restart**, and never affects an already open deal (OPEN never reads the
  provider).
- The production provider always reads the **current** database value:
  `BotRepository.get_deposit` reloads the row with
  `populate_existing=True`, because the long-lived live session
  (`expire_on_commit=False`) may still hold the `Bot` in its identity map
  and must not hand that copy to the engine (round-2 review correction B2).
- When the provider is not wired (generic engines / tests) the static
  `PositionSizing` source is used unchanged.
- Regression coverage: edit while RUNNING + FLAT → next entry uses the new
  value (no restart); edit while OPEN → exit repeats unchanged, the next FLAT
  entry uses the new value; deposit cleared while OPEN → the exit is
  unaffected, the next FLAT entry fails with `SizingNotConfigured`; B2
  two-session regression — an edit committed through a separate per-request
  session is returned by the production provider (a plain `get` still hands
  back the stale identity-map copy).

### C7 (round-2). Snapshot trimmed to exactly `lookback_bars` (GitHub Issue #3)

- Carry-over from MVP-6.10 (GitHub Issue #3): the retrieval window is one bar
  wider than the configured lookback (to account for the forming bar), so the
  broker may return `lookback_bars + 1` candles.
- `MarketDataService.get_snapshot()` now trims the received candles to the
  newest `lookback_bars` (`candles[-lookback_bars:]`) after the non-empty
  check: the snapshot contains exactly `lookback_bars`, chronological order
  preserved, newest candle retained last. Fewer-than-`lookback_bars` candles
  are kept as-is (the non-empty contract stays).
- Regression coverage: the broker returns `lookback_bars + 1` candles → the
  snapshot contains exactly `lookback_bars`, the newest last, contiguous and
  chronological. GitHub Issue #3 stays open until the fix is published to
  `master`.

### Testing

`tests/test_mvp611_deposit_sizing.py` (38 tests) covers the approved
contracts and the round-1 correction: SIMPLE split with/without martingale
(nominals and the sum == D), CUSTOM split and the >100% block, the explicit
SIGNAL block, sizing independence from the DCA engine math, lot rounding
down, the below-lot whole-entry block (error message content), missing
lot/currency blocks, deposit None/0/negative -> `SizingNotConfigured`, API
validation (422 for non-positive, 422 for a PATCH without the deposit key,
persist/clear), UNKNOWN -> no intents, FLAT + no active orders -> entry via
the Risk Manager (with lot-rounded quantities), FLAT + active bot orders ->
no entry (and re-entry after the order is filled/terminal), absent position
without reconciliation -> UNKNOWN, OPEN -> exit only, sign mismatch -> no
intents, unchanged Backtest-style evaluation, B1 regressions (OPEN + deposit
unset / SIGNAL / CUSTOM-over-100% -> exit submitted; FLAT + deposit unset ->
`SizingNotConfigured`) and C6 regressions (deposit edit applies from the next
FLAT entry without a restart; edit while OPEN affects only the next deal;
deposit cleared while OPEN keeps the exit, the next FLAT entry is blocked)
and the B2 two-session regression (a deposit edit committed through a
separate per-request session is returned by the production provider while a
plain `get` still returns the stale identity-map copy).
`tests/test_mvp69_position_state.py` and
`tests/test_mvp610_market_snapshot.py` were updated for the explicit
reconciliation (the OPEN state now requires `mark_reconciled`; an OPEN cycle
submits the exit only, no new grid); `test_mvp610_market_snapshot.py` also
covers C7 (broker returns `lookback_bars + 1` candles -> the snapshot
contains exactly `lookback_bars`, the newest last).


## 30. Live deal continuation (simple TP, simple/custom grid) — MVP-6.12

This section records MVP-6.12 (approved contracts D1–D7, 2026-09-30, GitHub
Issue #7): the live cycle is no longer "entry + exit intents from the
strategy" — a position cycle is one **Deal** owned by the new Deal layer,
from the FLAT entry fill to the take-profit fill. The grid is built up
front from the entry snapshot price, the deposit is captured at deal entry
(C6), the take-profit belongs to the Deal (never to the strategy plan), and
all live prices are tick-aligned in the safe direction (D3).

### D1. Supported configuration (explicit rejection at START)

- Live deal continuation applies only when: `DCAGridConfig.mode` is
  `SIMPLE` or `CUSTOM`; `ExitConfig.take_profit.kind == "fixed_percentage"`;
  `stop_loss is None`; `signal_stop is None`; and
  `pull_up_percent == 0`. Anything else raises
  `app.trading.deal.DealConfigUnsupported` at bot START.
- `app/api/bots.py:_apply` maps `DealConfigUnsupported` to HTTP 409 with the
  explicit message "config not supported for live deal continuation: ..."
  and persists the actual runtime state (ERROR). No default strategy config
  is invented; the validation lives at the composition boundary
  (`app/trading/live_execution.py`) where the DealManager is wired.

### D2. Deal lifecycle (one persisted Deal per position cycle)

- A Deal is one position cycle: FLAT entry fill → closing TP fill. It is
  persisted (`app/models/deal.py`, Alembic `0005_deal_continuation`,
  `app/persistence/deal_store.py`) with Decimal prices/quantities and UTC
  timestamps; `DealStatus` is OPENING → OPEN → CLOSED (plus ERROR).
- Entry: the whole grid is built from the snapshot price in one
  `DCAGridEngine.build` call (per-level nominal = deposit split per C2),
  every level passes C3 (lot rounding) + D3 (tick alignment), any failure
  blocks the whole entry (`DealError`). The Deal is persisted **before** any
  order is submitted; then the first level order + up to `active_limit`
  working levels are placed. The strategy `Plan` grid/exits must not be
  submitted by the engine afterwards (see D6).
- Entry fill (`OrderManager.on_trade_fill` → `apply_fill` → synchronous
  `fill_listener` queue) → Deal OPEN → TP placed (D4).
- DCA fill (partial or full) → TP re-armed (D4) and the next waiting level
  is placed so the number of working levels stays at `active_limit`.
- TP partial fill → the TP keeps working; position reaches zero → remaining
  grid orders are cancelled → Deal CLOSED → the cycle returns to the FLAT
  entry path for the next deal.
- Correlation: `bot_id` + deterministic intent ids
  (`deal-{id}-grid-{index}`, `deal-{id}-tp-{rev}`) — no broker types enter
  the deal layer.

### D3. Tick alignment (round in the safe direction)

- Every limit price is a multiple of `Instrument.tick_size`, rounded in the
  safe direction: grid LONG down / SHORT up; TP LONG up / SHORT down.
  Rounding is `Decimal`-only (`round_down_to_tick` / `round_up_to_tick` /
  `align_grid_price` / `align_tp_price` in `app/trading/deal.py`).
- A missing or non-positive tick size is an explicit `DealTickSizeInvalid`
  error (no invented default), and blocks the entry before any order is
  submitted.

### D4. Take-profit ownership (Deal-owned, position-authoritative)

- The TP is **one** limit order for the whole current position quantity
  (from the PositionManager, lot-rounded down), priced
  `average_price × (1 ± tp%)` (LONG +, SHORT −) from the PositionManager
  **average** — never the market price — then D3-aligned.
- Re-arm on every grid fill: cancel the old TP, await confirmation (or a
  terminal state), then place the new one. If the old TP filled during the
  cancel, the new TP is recomputed from the actual (reduced) position.
- Invariant: never two working TPs. If a cancel fails or the TP state is
  unknown, no second TP is placed, the bot's new submissions are blocked,
  and the deal is marked as needing reconciliation (`DealBlocked`).

### D5. Recovery (no blind grid recreation)

- `LiveRecoveryCoordinator` recovers after order/position reconciliation:
  non-CLOSED Deals are loaded, broker facts are matched level-by-level, and
  no grid is recreated blindly. A still-active grid order stays as-is; a
  broker-filled grid order is applied as a fill (→ TP re-arm per D4); a
  missing TP while OPEN is placed once after successful reconciliation.
- Unknown state / contradiction → the bot goes to ERROR and new submissions
  are stopped (`DealReconciliationRequired` / `DealPositionContradiction`).

### D6. Engine boundary (live OPEN creates no exit intents)

- The live per-bot `TradingEngine.process()` in OPEN must NOT create exit
  intents from `StrategyEngine.evaluate()` — the TP is Deal-owned. The
  engine-level "exits from market price" behavior and its tests were
  removed; backtest/generic engines are unchanged.
- Cleanup: the unreachable duplicate in `make_deposit_provider()`
  (`app/trading/live_execution.py`) was removed.

### D7. Reducing intents are exempt from growth limits (owner contract)

- A **reducing** intent — the Deal's closing take-profit and any other order
  that reduces the current live position — is exempt from `max_position_size`
  and `daily_loss_limit` (Risk Manager §10.1 checks 5–6): `check_order()`
  skips them when the PositionManager position for the intent's FIGI is
  non-zero, the intent side is opposite to the position sign, and
  `quantity <= |position|`. Checks 1–4 (emergency stop, quantity, price,
  instrument permission) still apply; non-reducing intents keep the full
  MVP-6.6 behavior; without a known position no exemption is applied.
- Rationale: the TP is the safety exit of a Deal — a growth limit must never
  block the closing leg (a rejected TP would leave the position without a
  take-profit).

### Correction round 1 (independent review, 2026-09-30)

- **B1 (TP re-arm safety / event isolation):** the new TP is computed and
  risk-gated **before** the working TP is cancelled; a risk rejection keeps
  the old TP working (the position is never left uncovered) and surfaces as
  `DealOrderRejected`. `DealManager.pump()` now isolates every event: one
  reaction failure marks exactly that Deal ERROR (and the bot), and the
  remaining queued events are still applied — a bad fill no longer escapes
  the stream's ``on_event`` hook or starves the rest of the batch.
- **B2 (no silent deal failure):** every deal failure (`pump()`,
  `open_deal()`, recovery) funnels through `DealManager._fail_deal`: the bot
  lifecycle is notified (`BotRuntime.fail()` → ERROR, persisted via
  `BotRepository`), and the reason is observable as the read-only
  `deal_error` field in `GET /api/bots/{id}` (`BotResponse.deal_error`). An
  OPEN live position without an owning non-CLOSED Deal raises
  `DealPositionContradiction` and puts the bot in ERROR instead of being
  silently ignored (replaces the former D6 no-op cycle behavior).

### Correction round 2 (independent review, 2026-09-30)

- **B3 (a fill is a broker fact; the TP is never larger than the position):**
  - `OrderManager`/domain: `CANCEL_REQUESTED → PARTIALLY_FILLED / FILLED` is
    now an allowed transition — a fill that arrives while the cancel is in
    flight (exchange race) is applied instead of raising
    `OrderStateError`. A fill reported for an order already in a terminal
    state (e.g. `CANCELLED`) is still applied to the position and recorded,
    keeping the terminal state. `OrderManager.cancel()` no longer overwrites
    a terminal outcome: after the broker call it transitions to `CANCELLED`
    only while the order is still live.
  - `DealManager._rearm_tp()`: after the old-TP cancel returns (confirmed or
    terminal) the position is **re-read**; zero → `_close_deal` (no new TP);
    changed quantity/average → the intent is rebuilt at the next `tp_rev` and
    risk-gated again (D7 keeps the reducing TP allowed). The new TP can never
    exceed the actual position. Recovery no longer re-registers a Deal that
    `_close_deal` just closed (it would block the next entry).

### Tests (validation commands)

Run from `backend/` with the project venv:

- `./.venv/Scripts/python.exe -m pytest tests/test_mvp612_deal_continuation.py -q`
  — D1–D7 coverage (START 409 / SIMPLE+CUSTOM accepted, tick alignment both
  directions + missing tick, whole-grid C3/D3 check before submission,
  persist-before-submit, deposit recapture per deal, active_limit level
  promotion, TP re-arm on DCA fill, TP partial-fill continuation, TP-fills-
  during-cancel race, position-zero close, recovery matching, engine
  no-exit-intents; correction round 1: D7 reducing exemption through a real
  Deal, B1 risk-rejected re-arm keeps the old TP and isolates a failing
  batch, B2 deal_error observability + OPEN-without-Deal ERROR).
- `./.venv/Scripts/python.exe -m pytest tests/test_trading_risk.py -q` — D7
  unit coverage (reducing sell/buy exempt from position size and daily loss;
  increasing intent blocked; quantity beyond the position is not reducing;
  emergency stop / blocked instrument still block reducing intents).
- `./.venv/Scripts/python.exe -m pytest tests/test_mvp69_position_state.py tests/test_mvp611_deposit_sizing.py tests/test_mvp610_market_snapshot.py -q`
  — updated for D6: the OPEN live cycle submits no exit intents any more
  (MVP-6.11 B1/C6 exit-only assertions replaced by the Deal-owned TP
  coverage; `test_mvp610_market_snapshot.py` asserts no order is placed for
  the OPEN cycle).
- `./.venv/Scripts/python.exe -m pytest -q` — full backend suite.
- `ruff check app tests scripts` (from `backend/`), `alembic heads` (single
  head, `0005`), `npm run build` (frontend unchanged, stays green).

## 31. Live cycle scheduler — MVP-6.13

This section records MVP-6.13 (approved contracts S1–S5, 2026-09-30, GitHub
Issue #9; S6 and round-1 corrections B1/B2/B3 added 2026-10-01 by the round-1
review): **when** a RUNNING bot's strategy cycle runs is decided by a new
broker-neutral `LiveCycleScheduler` (`app/trading/scheduler.py`); it never
changes *what* runs. The scheduler calls the existing
`BotRuntime.execute_strategy(MarketContext)` once per tick with a
broker-neutral context built from the raw market snapshot (MVP-6.10
`market_snapshot_to_context`), and the MVP-6.11/6.12 gates (risk, deposit,
deal) stay authoritative.

### S1. Scheduler runtime and correctness guards

- The scheduler is started by the application lifespan **only after a SAFE
  startup recovery**, next to the stream task, and is stopped on shutdown
  (`app/main.py`). Per-bot pass tasks use the same long-lived DB session, so
  the scheduler is cancelled before the stream shutdown closes the session.
- One strategy cycle per tick per bot; each bot's pass runs in its own
  asyncio task, so a slow or failing bot never delays another.
- At most one cycle per bot at a time: a tick that arrives while the
  previous pass is still in flight is **skipped** (no catch-up of missed
  ticks). The in-flight marker is a per-bot id set claimed synchronously in
  `advance()` (the per-bot ticker is created inside the pass task, so it
  cannot carry the marker itself).
- Only `RUNNING` bots are ticked (STOPPED / ERROR / EMERGENCY_STOP are
  skipped).
- The scheduler never ticks while the safety gate is closed
  (`safety_gate=service.can_execute`); `LiveExecutionService.run_scheduler_forever()`
  raises `LiveExecutionBlocked` before a SAFE recovery or when no scheduler
  is wired.

### S2. Tick timing by calculation method

- `AT_BAR_CLOSE`: one tick per bar of the bot's configured timeframe, due at
  the UTC bar boundary + `bar_close_delay_seconds` (default 5). The
  just-closed bar must be present in the raw `MarketSnapshot` with
  `is_complete is True` — a `None` completeness counts as **not confirmed**
  (the `market_snapshot_to_context` None→True mapping must not be used for
  confirmation). Confirmation is a timestamp **range** check, not exact
  equality (B1): a complete candle whose start lies inside the bar interval
  (`[bar_start(boundary − 1 s), boundary)`) is accepted, so a broker that
  stamps day/week/month bars at a non-epoch-aligned start (e.g. a day candle
  at 03:00 UTC) is still confirmed. Unconfirmed ticks are retried every
  `bar_close_retry_seconds` (default 5) up to
  `bar_close_max_wait_seconds` (default 60) after the boundary, then skipped
  and counted as one transient failure (S4) — but see S6: a boundary whose
  tick fell while the instrument was not tradable is exempt from the
  max-wait rule.
- `PER_MINUTE`: one tick at each UTC minute boundary; the forming bar is
  used as-is (`FilterEvaluator` semantics unchanged).
- Ops parameters (settings, non-financial): `scheduler_bar_close_delay_seconds=5`,
  `scheduler_bar_close_retry_seconds=5`,
  `scheduler_bar_close_max_wait_seconds=60`,
  `scheduler_max_consecutive_failures=3`.

### S3. Trading-session gate (no hard-coded schedule)

- Before every tick the scheduler asks the broker via the new abstract
  `BrokerAdapter.get_trading_status(figi)`.
- `TRADING_UNAVAILABLE` → the tick is **deferred** (S6): not dropped, not
  counted as a failure; it runs exactly once at the next tradable moment,
  on the closed bar of the deferred boundary. While the instrument is not
  tradable the deferral persists; a failed/unknown status is counted as a
  transient (S3/S4) but does not drop the deferral.
- A failed or unknown status → skip + count one transient failure (S4).
- T-Invest implementation: `MarketDataService/GetTradingStatus`, mapped
  inside `TInvestAdapter`; only `SECURITY_TRADING_STATUS_NORMAL_TRADING`
  with `api_trade_available_flag == true` is tradable, every other
  documented exchange state maps to `TRADING_UNAVAILABLE`, and `UNSPECIFIED`
  or an unrecognized value raises `BrokerApiError` (unknown must never be
  silently "not tradable"). No exchange session schedule is hard-coded.
- The backtest broker returns `TRADING_AVAILABLE` (no session concept).

### S4. Failure policy

- Transient failures — `MarketDataUnavailable`, broker transport errors
  (the broker-neutral `BrokerTransportError` marker: `BrokerConnectionError`,
  `RateLimitError`, `BrokerApiError`), network timeouts, a closed bar not
  confirmed within max wait, an unknown trading status — are counted per bot
  in memory; after `scheduler_max_consecutive_failures` (default 3)
  consecutive ones the bot goes to ERROR (production callback:
  `BotRuntime.fail` + `BotRepository` ERROR; without a callback the
  scheduler falls back to `BotRuntime.fail`).
- Non-transient failures (`TimeframeNotConfigured`, `LookbackNotConfigured`,
  `SizingNotConfigured`/`SizingError`, `DealConfigUnsupported`,
  `RiskRejected`, `BotStateError`, unexpected exceptions) fail the bot
  immediately.
- A successful cycle resets the counter; S3 UNAVAILABLE skips do not count.
- Observability: a generic read-only `last_error` field was added to
  `GET /api/bots/{id}` (`BotResponse.last_error`, fed by
  `LiveCycleScheduler.last_error_for`) — distinct from the deal-specific
  `deal_error` (B2). It is absent when the live service is not running.

### S5. Correctness ("what runs" is unchanged)

- The scheduler decides only *when* a cycle runs and never touches
  entry/grid/TP/Deal/Risk semantics; the MVP-6.11/6.12 gates remain
  authoritative.
- Clock and sleeps are injectable (`Clock` protocol, `SystemClock`
  production); tests never sleep real time.
- Broker neutrality: `app/trading` facing code imports only
  `app.brokers.base` (and the `BrokerTransportError` marker), never
  `app.brokers.tinvest*`; T-Invest types stay inside the adapter
  (`build_live_service` is the documented composition exception).

### S6. AT_BAR_CLOSE deferral (round-1 correction B1)

- Motivation (review B1): a `DAY_1` bar closes at 00:00 UTC = 03:00 MSK —
  always outside the MOEX session, because the bar close includes the
  calendar boundary, not a session close. Before the correction the S3 skip
  concluded the boundary without a tick, so a DAY_1 bot would never run a
  cycle at all (same for any bot whose boundary falls while the market is
  closed).
- Behavior: when the tick falls while `get_trading_status` returns
  `TRADING_UNAVAILABLE`, the tick is **deferred** — the boundary stays
  pending, `deferred=True`, no failure is counted, no snapshot is fetched.
  The scheduler re-checks the status at its 1 s cadence; the moment the
  instrument is tradable again the deferred tick runs **exactly once** on the
  closed bar of the deferred boundary. The S2 max-wait timeout does not apply
  to a deferred tick (it was deferred, not lost); if the bar is not yet
  confirmed the confirmation retries on the next pass.
- The deferred boundary is **fixed**: while deferred the scheduler does not
  recompute the boundary from the clock, because a closed session passes no
  newer closed bar. When several bar boundaries pass in a row while the
  session is closed, only one deferred cycle runs for the last bar that
  actually closed (no catch-up; S1 "no catch-up" preserved).
- A newer boundary supersedes an older still-pending (non-deferred) one
  without a failure count: only the latest pending boundary is kept (no
  catch-up of missed bars).
- Round-2 correction **B4** (see below): the deferred tick runs on the
  **latest closed bar** (a complete candle that started before the deferred
  boundary), not on a candle inside the deferred bar's own range, and the
  deferral is bounded so a bot is never stuck while trading is open.

### B4. Deferred tick runs on the latest closed bar, with a bound (round-2 correction)

- Motivation (review B4): a bar without trades has **no candle** (T-Invest has
  no empty candles). The round-1 rule confirmed the deferred tick only by a
  candle inside the deferred bar's own range, so a no-trade last bar before a
  session close left the deferred tick unconfirmed forever — the bot stalled
  silently in `deferred` (reproduced on the MVP-6.13 harness: executions=0
  with `TRADING_AVAILABLE` at +14 h/15 h/16 h/20 h/48 h).
- Fix 1: once the instrument is tradable, the deferred tick is confirmed by
  the **latest closed bar** — the raw snapshot contains at least one candle
  with `is_complete is True` and `timestamp < deferred boundary` (`_latest_closed_bar_before`).
  The cycle then runs exactly once on that data and the boundary is concluded.
- Fix 2 (bound): while the instrument is tradable, if no such candle exists
  yet and a **newer** bar boundary has already passed (the bar containing
  `now − delay` starts after the deferred boundary), the deferral is concluded
  with **one transient failure** (S4 counted) and normal boundary processing
  resumes on the next pass. A deferred bot is never stuck while trading is
  open; the transient count is part of the same per-bot S4 counter. Amended by
  B6.2 (round 4): the bound only applies after a full bar + `max_wait` from
  the **first tradable moment** (see the B6 section below).
- B4 does not change the non-deferred S2 path: an unconfirmed non-deferred bar
  still retries up to `max_wait` and then counts one transient failure.
- S6 tests from round 1 stay green: they already carry a complete candle
  before the deferred boundary, which the B4 rule accepts as well.

### B5. Empty snapshot in the deferred path is "not confirmed yet" (round-3 correction)

- Motivation (review B5): right after a session reopens the production
  snapshot provider (`MarketDataService.get_snapshot`, MVP-6.10/C7) requests
  candles in a **wall-clock window** of `(lookback_bars + 1) × timeframe`
  before "now". For an intraday bot that window lies inside the night/weekend
  gap (M5 with `lookback_bars = 50` gives ≈ 4 h 15 m against a 7–10 h night
  gap), so the provider raises `MarketDataUnavailable("no candle history")`
  on every 1-s scheduler pass. In the deferred path that was counted as a
  transient failure per pass → the bot went to ERROR within ~3 s of the
  session opening (reproduced: `3 consecutive transient cycle failures (last:
  no candle history (night gap))`).
- Fix: while tradable, an unavailable/empty snapshot
  (`MarketDataUnavailable`) or a snapshot with no closed bar before the
  deferred boundary is **"not confirmed yet"** in the deferred path — never a
  per-pass failure. Only the B4 bound (a newer boundary has passed) concludes
  the deferral with **one** transient failure; normal boundary processing then
  resumes.
- Consequence of the MVP-6.10 wall-clock window (documented): for intraday
  bots the pre-close bars are usually **outside** the window at reopen, so the
  deferred tick is in practice **concluded by the B4 bound** rather than run.
  `DAY_1` (window ≈ `lookback_bars` days) is unaffected. Fetching the snapshot
  **by bar count across session gaps** is a separate follow-up — it also
  affects indicator input right after gaps (out of scope of MVP-6.13).

### B6. One transient failure per tick; deferred poll cadence and bound-relative-to-reopen (round-4 correction)

- Motivation (review B6, three related defects):
  1. `_confirm_boundary()` called the snapshot provider without handling — a
     `MarketDataUnavailable` or broker transport error on a **retry attempt**
     was counted on **every 5-s retry slot** (S4: "3 consecutive transient
     failures" must mean three **ticks**, not three retries of one tick). One
     quiet bar (no trades yet) → ERROR in ~15 s.
  2. The B4 bound (a newer bar boundary has passed) fires **immediately at the
     session reopen** — after a night/weekend gap, many boundaries have
     already passed, so the deferral was concluded on the first tradable pass
     and the retry-slot counting (defect 1) added the rest.
  3. The deferred path re-checked `GetTradingStatus` on every **1-s** pass for
     the whole closed session — a rate-limit storm; a rate-limit error counted
     as a transient per pass → possible ERROR.
- Fix 1 (B6.1): a tick is **at most one transient failure**. Inside the retry
  window of `_confirm_boundary()`, a transient data failure
  (`MarketDataUnavailable`, transport error, still-unconfirmed bar) is
  **"not confirmed yet"** — no count; exactly **one** transient is counted when
  `max_wait` expires without a successful cycle. A **non-transient** error
  still fails the bot immediately (S4). `PER_MINUTE` was already one failure
  per minute tick at most (one attempt claimed per minute); the S4 threshold
  now means three consecutive **quiet bars** → ERROR, not three retry slots
  of one bar.
- Fix 2 (B6.2): the deferred tick records the **first tradable moment**; the
  B4 bound may conclude the deferral only **after a full bar of trading has
  passed from that moment, plus the normal `max_wait`**
  (`_bar_start(first_tradable) + timeframe + max_wait`). The reopen therefore
  gets a full bar (+ max_wait) of data time before the conclusion — the bot is
  never dropped within seconds of the session opening, and still never stuck
  while trading is open.
- Fix 3 (B6.3): while deferred, the trading status is polled at the **retry
  cadence** (`bar_close_retry_seconds`, 5 s) instead of every 1-s pass, and a
  failed/rate-limited status counts **at most once per bar boundary** — a
  persistent status failure over one bar is ONE transient (three consecutive
  bar boundaries still trip the S4 threshold).
- Amends the B4 "newer boundary" wording above: the bound is now relative to
  the first tradable moment (B6.2), and the B5 "one transient" conclusion only
  applies via that bound.


### B2. Shared live-session serialization (round-1 correction)

- The production live graph shares ONE long-lived `AsyncSession`
  (`build_live_service`) between the stream, the scheduler passes and the API
  lifecycle paths. An `AsyncSession` is **not safe for concurrent use**
  (the round-1 reviewer reproduced overlapping operations raising
  `ResourceClosedError`/`IllegalStateChangeError` on PostgreSQL when several
  bot passes hit the session at once).
- Fix: `build_live_service` creates one `asyncio.Lock` (`session_lock`) and
  passes it to `BotRepository`, `SqlAlchemyDealStore`,
  `SqlAlchemyLiveStateStore` (optional keyword-only `lock` parameter;
  default `None` keeps tests and per-request API sessions unchanged).
  Every repository/store operation — including the multi-await
  `update_state` commit/refresh and the `save_snapshot` upsert loop — runs
  inside the lock. Direct `session.get(...)` calls in
  `build_live_service` (`_session_get`, `_load_strategy`) are wrapped the
  same way.
- MVP-6.11 C6/B2 guarantee preserved: `get_deposit` still reads with
  `populate_existing=True` (fresh deposit, no identity-map copy).

### B3. Scheduler state reset on bot state change (round-1 correction)

- A bot that left RUNNING (ERROR / STOPPED / EMERGENCY_STOP) must not carry
  its in-memory scheduler state into its next START. `advance()` observes
  every bot state change and resets the per-bot ticker: failure counter,
  pending/deferred boundary, retry index and PER_MINUTE claim.
- `last_done_boundary` is intentionally **kept**: a concluded bar is never
  ticked twice after a restart.
- Consequence: after a restart the transient-failure counter starts from 0
  (3 consecutive failures are needed again, S4 threshold unchanged) and a
  deferred tick does not leak across the restart.

### Known limitations (documented, not changed)

- `market_snapshot_to_context()` maps `is_complete is None → True`; S2
  confirmation deliberately reads the raw `MarketSnapshot` instead, so the
  confirmation rule and the context mapping can disagree on a `None`
  completeness without a warning.
- WEEK_1 / MONTH_1 tick boundaries are calendar-aligned (ISO Monday 00:00
  UTC / the 1st of the month 00:00 UTC) and MIN_1..DAY_1 are fixed UTC
  intervals from the epoch. This is an **assumption** (see the next bullet);
  the official T-Invest documentation does not confirm the start-stamp rule
  for WEEK_1/MONTH_1 and states no start rule at all for 2h/4h.
- On scheduler start, a bar whose confirmation window has already expired is
  skipped and counted as one transient: the scheduler cannot know whether
  that tick ran before the restart (a boundary that expired while the market
  was closed is deferred instead — S6).
- S6 scope: the deferral applies to `AT_BAR_CLOSE`; `PER_MINUTE` keeps the S3
  skip-without-count on a not-tradable minute. Verified from the official
  T-Invest docs: `Candle.time` is «Время начала интервала свечи по UTC»
  (marketdata.proto) and the FAQ states that for `CANDLE_INTERVAL_DAY` the
  `from`/`to` fields are ignored, so day candles are whole calendar days.
  The exact start timestamps of WEEK_1/MONTH_1 candles (and any start rule
  for 2h/4h) are **not** stated in the official documentation, so a
  broker-side non-epoch-aligned stamp for those bars is verified indirectly
  via the B1 range-confirmation rule — the scheduler never assumes exact
  equality.

### Tests (validation commands)

- `./.venv/Scripts/python.exe -m pytest tests/test_mvp613_scheduler.py -q`
  — S1–S6 coverage (tick at boundary+5 / exactly once per bar, retry every
  5s until confirmed, skip+count at max wait, `is_complete=None` not
  confirmed, range confirmation of a non-midnight day candle (B1), deferral
  when not tradable and one cycle at the next tradable moment (S6, incl.
  DAY_1 and several closed-session boundaries), PER_MINUTE once per minute,
  unknown/failed status counted, 3 consecutive transients → ERROR, reset on
  success, non-transient immediate ERROR, B3 reset after ERROR + restart,
  B2 shared-session overlap detection with/without the live lock, overlap
  skip / no parallel cycles, slow and failing bot isolation, only RUNNING
  ticked, gate closed / not SAFE start, T-Invest `GetTradingStatus` mapping,
  backtest no-session).
- `./.venv/Scripts/python.exe -m pytest -q` — full backend suite.
- `ruff check app tests scripts` (from `backend/`), `alembic heads` (single
  head), `npm run build` (frontend unchanged, stays green).

## 32. No-trade bars are skipped, not failures — MVP-6.14

This section records MVP-6.14 (owner-approved contract N1–N3, 2026-10-01,
GitHub Issue #11): on MOEX/T-Invest a bar interval without trades has **no
candle** — the MVP-6.13 scheduler therefore treated an ordinary quiet period
as "not confirmed" and, after `max_wait`, cost one transient failure per bar
(3 consecutive bars → bot ERROR). The owner decision: a **proven** no-trade
bar is a **skipped tick** — no strategy cycle, no failure count, the
consecutive-failure counter is not reset — and the reason is observable via a
read-only `last_skip_reason` in `GET /api/bots/{id}`. Proof is only ever from
broker facts; an unproven no-trade case keeps the MVP-6.13 behaviour unchanged
(a lagging data feed must still be detected).

### N1. A proven no-trade bar is a skipped tick

- A target bar `[bar_start, boundary)` (the same B1 confirmation range,
  `bar_start = _bar_start(boundary - 1 s, tf)`) counts as **proven no-trade**
  when the snapshot request succeeded **and**:

  - (a) the snapshot has **no candle** in `[bar_start, boundary)` (a candle
    present, even incomplete, disproves it), **and**
  - (b) either a candle with `start ≥ boundary` exists (the broker's data is
    already past the target bar — the forming candle of the next bar counts),
    **or** the broker's last-trade time is known and `< bar_start` (no trade
    since before the bar began).

- Proven → the tick is **skipped** at once: no strategy cycle, no failure
  count, the consecutive-failure counter is **not reset** (a skip is neither a
  success nor a failure), no `max_wait` wait, and the boundary is concluded
  (the bar is never retried). The reason is stored per bot in memory and
  exposed read-only as `last_skip_reason` in `GET /api/bots/{id}`
  (`LiveCycleScheduler.last_skip_reason_for`).
- **Empty window**: an empty candle window (`NoTradesInWindow`, see N2) counts
  as proven no-trade when the last-trade time is known and earlier than the
  window start. If the last-trade time is unknown (`None`), nothing is proven.
- Not proven (no newer candle, last trade unknown or inside/after the bar) →
  the existing MVP-6.13 behaviour applies: wait until `max_wait`, then one
  transient failure. A lagging feed is still detected.

### N2. Broker facts (no inference)

- `MarketSnapshot` gains `last_trade_at: datetime | None` — the broker's
  last-trade timestamp, `None` when the broker gave none. It is a separate
  field: the existing `timestamp` field keeps its MVP-6.10 meaning and
  fallback (`last.timestamp or newest candle timestamp`). The value comes from
  `LastPrice.timestamp`, which `TInvestAdapter._to_last_price` fills from the
  T-Invest `GetLastPrices.lastPrices[].time` field (the official last-trade
  time, decoded by `_timestamp_to_datetime` into timezone-aware UTC).
- `MarketDataService.get_snapshot()` keeps raising `MarketDataUnavailable` for
  an empty window, but raises a **subclass** `NoTradesInWindow(
  MarketDataUnavailable)` carrying `last_trade_at` and `window_start` when the
  last price is usable and the window has no candles. All existing
  `MarketDataUnavailable` handling keeps working unchanged (it is a subclass;
  the message text is unchanged).
- No change to the snapshot trimming (C7), the lookback contract or the
  wall-clock retrieval window.

### N3. Where it applies

- `AT_BAR_CLOSE`, normal path: N1 is checked on each confirmation attempt
  (`_confirm_boundary`); a proven no-trade bar concludes the tick as a skip at
  once. An unproven no-trade case keeps the retry/`max_wait` behaviour (and
  the B6.1 one-transient-per-tick semantics).
- `AT_BAR_CLOSE`, deferred path (S6): **unchanged** — a no-trade bar (or
  `NoTradesInWindow`) while deferred is "not confirmed yet"; the S6/B4/B5/B6
  rules decide. No skip is recorded on the deferred path.
- `PER_MINUTE`: a `NoTradesInWindow` whose `last_trade_at < window_start` is a
  skip, not counted — the forming bar without any candle is not a failure. An
  unproven one is counted as before (S4 classification, 3 per-minute
  transients → ERROR).
- Nothing else changes: S1–S6, the B1–B6 rules, the failure threshold, and
  the Deal / Risk / strategy semantics are untouched.

### Tests (validation commands)

- `./.venv/Scripts/python.exe -m pytest tests/test_mvp614_no_trade_bar.py -q`
  — N1/N2/N3 coverage: skip with a newer candle (incl. the forming incomplete
  candle), skip with a last trade before the bar start, unproven no-candle →
  one transient at `max_wait`, lagging feed (last trade inside the bar) not
  proven, 10 proven skips neither increment nor reset the counter (2 failures
  + skips + 1 failure → ERROR), proven-quiet empty window skipped at
  `AT_BAR_CLOSE` and `PER_MINUTE`, unproven empty window keeps the
  `MarketDataUnavailable` behaviour (bar close: one transient at `max_wait`;
  per minute: 3 transients → ERROR), deferred path unchanged
  (`NoTradesInWindow` = "not confirmed yet", then the B4 cycle runs on
  recovery), `get_snapshot` raises `NoTradesInWindow` with the fields and
  fills `last_trade_at` from `LastPrice.timestamp`.
- The MVP-6.13 scheduler tests (`tests/test_mvp613_scheduler.py`) stay green
  unchanged: S6/B4/B5/B6 semantics are preserved.
- `./.venv/Scripts/python.exe -m pytest -q` — full backend suite.
- `ruff check app tests scripts` (from `backend/`), `alembic heads` (single
  head, no new migration), `npm run build` (frontend unchanged, stays green).

## 33. Snapshot by bar count with trading breaks — MVP-6.15

This section records MVP-6.15 (owner-approved contract L1–L4, 2026-10-02,
GitHub Issue #13). Under MVP-6.10 the snapshot asked for candles in a
**wall-clock window** `(lookback_bars + 1) × timeframe` back from "now".
MOEX is not a round-the-clock market, so right after a night break, a weekend
or a holiday the window fell wholly or partially inside the break:

- indicators received **fewer** bars than `StrategyConfig.lookback_bars`
  (morning signals were computed on incomplete history);
- the S6 deferred tick (MVP-6.13) of an intraday bot almost never saw the last
  bar before the close and was usually resolved by the B4 bound instead of
  running;
- an empty window after the night produced `NoTradesInWindow` /
  `MarketDataUnavailable` where the history actually existed.

The owner decision: the snapshot is defined **by the number of bars**, not by
the clock. The MVP-6.10 contract "a wall-clock window of candles" is **replaced**
by "the last `lookback_bars` candles that actually exist at the broker".

### L1. The snapshot is the last `lookback_bars` existing candles

`get_snapshot(figi, timeframe, lookback_bars)` returns the `lookback_bars`
newest candles that actually exist at the broker, regardless of trading
breaks. The forming candle is included as before; chronological order and the
C7 trim (exactly `lookback_bars`, newest kept) are preserved. No candles
"across the break" are invented.

### L2. Backward fill, depth-bounded

- First the existing window `(lookback_bars + 1) × timeframe` is requested, as
  before. If it already holds `lookback_bars` candles, there are **no**
  additional requests.
- Otherwise the search is extended **backwards** (an already requested disjoint
  range is never re-requested) until `lookback_bars` candles are collected or
  the maximum search depth is reached.
- Maximum depth: `max(snapshot_min_search_days × 86400 s,
  snapshot_search_factor × lookback_bars × timeframe duration)`. For M5 with
  `lookback 50` that is 14 days; for D1 with `lookback 200` about 800 days.
  Both numbers are ops parameters in application settings
  (`Settings.snapshot_min_search_days = 14`,
  `Settings.snapshot_search_factor = 4`).
- The expansion step chosen by the coder: disjoint windows of
  `_TIMEFRAME_CHUNK_SECONDS[timeframe]` (the provider's per-request maximum,
  so each step is a single broker request). Expected request counts in typical
  scenarios: **1** when the first window suffices; **2** on a morning after a
  night break or a Monday after a weekend (M5, `lookback 50` — one 7-day chunk
  reaches into the previous session); **3** for a new listing whose history is
  shorter than the depth, or when the whole depth is empty.

### L3. History shorter than `lookback_bars`

If even at the maximum depth there are fewer than `lookback_bars` candles, the
snapshot returns **what exists**. This is not an error: as from MVP-6.10,
indicators with insufficient history simply produce no signal.

### L4. Empty result and MVP-6.14

- `NoTradesInWindow` is raised only when there is **no candle at all** over the
  whole searched depth. `window_start` = the start of the searched depth;
  `last_trade_at` — as in MVP-6.14 (from `LastPrice.timestamp`).
- The proven-empty-bar rule (N1) and the deferred tick (S6/B4–B6) are
  **unchanged**; they simply start seeing the candles before the break.

### Implementation notes

- `MarketDataService` gained an injectable `Clock` (same pattern as the
  scheduler clock) so snapshot tests are deterministic; production uses
  `datetime.now(UTC)`.
- The only changed existing test: `test_correct_snapshot_retrieval_request`
  (MVP-6.10) now feeds the broker more than `lookback_bars` candles — with the
  backward fill, fewer candles would no longer be a single-request scenario.

### Tests (validation commands)

- `./.venv/Scripts/python.exe -m pytest tests/test_mvp615_snapshot_bar_count.py
  -q` — L1–L4 coverage: single request inside a session, morning after a night
  break (50 candles from previous session, chronological), Monday after a
  weekend, new listing with short history (no error), empty whole depth →
  `NoTradesInWindow` with `window_start` = depth start, depth formula for M5/D1
  and from settings, and the S6 regression scenario (deferred at Friday close;
  Monday open runs exactly one cycle on the last bar before the close, no
  B4-bound conclusion).
- The MVP-6.10/6.13/6.14 suites stay green (only the one test above adjusted).
- `./.venv/Scripts/python.exe -m pytest -q` — full backend suite;
  `ruff check app tests scripts`; `alembic heads` (single head, no migration);
  `npm run build` (frontend unchanged).

## 34. Simple stop-loss in live trading — MVP-6.16

### Purpose

After MVP-6.12 a live deal only supports a simple TP; a stop-loss is rejected
at START (D1), so an averaging grid could run into a very large floating
drawdown. MVP-6.16 adds the **simple stop-loss** to the live deal as a real
broker-side stop order (T-Invest `StopOrdersService`).

Veles sources: «Стоп-лосс» help article — the simple stop is a market order
placed for the configured percent after **all grid orders are filled**; with a
15% grid overlap and a 5% stop-loss the trigger sits at −20% from the opening
price; a `stop_bot_after` setting controls what the bot does after the stop.

### E1. Stop level — from the opening price: overlap + SL

- **Opening price `P0`** — the actual average fill price of the deal's first
  order (level 0 of the Deal).
- **Stop distance** = `(offset_percent of the last grid level − offset_percent
  of level 0) + SL%`. For «Простой» this is exactly the overlap + SL; for
  «Свой» — the offset of the last order from the first one + SL.
- LONG: `stop = P0 × (1 − distance/100)`; SHORT: `stop = P0 × (1 + distance/100)`.
  Veles example: overlap 15% + SL 5% → the stop is at −20% from `P0`.
- Rounding to the price tick (project rule, by analogy with D3): towards the
  **earlier** trigger — LONG up, SHORT down. No `tick_size` → explicit error.
- The stop **arms only after all grid levels are filled** (every order of the
  Deal FILLED). Before that there is no stop order at the broker.

### E2. Execution — broker stop order

- New broker-neutral `BrokerAdapter` methods: `place_stop_order`,
  `cancel_stop_order`, `get_stop_orders`. `TInvestAdapter` implements them via
  `StopOrdersService` (`PostStopOrder` / `CancelStopOrder` / `GetStopOrders`):
  type **STOP_LOSS with market execution**, expiration **until cancelled**
  (`GOOD_TILL_CANCEL`). Mapping stays inside the adapter. `BacktestBroker`
  keeps a stub (the backtest does not use these methods).
- Stop quantity = **the whole current position** from `PositionManager`,
  rounded **down** to whole lots; never larger than the position.
- The stop order passes `RiskManager.check_order()`; as a reducing order it
  enjoys the D7 exemption.
- **Re-placement**: on any post-activation position change (partial TP) the
  stop order is replaced with the new position volume. Order as in
  D4/B1/B3: check the new order with Risk first, then cancel the old order and
  wait for the confirmation, then re-read the position and place the new order.
  Two simultaneous stop orders are not allowed. Unknown cancel result → bot
  ERROR (B2).
- **TP filled fully** → cancel the stop order → deal CLOSED.
- **Stop executed** (broker market fill) → cancel the TP → deal CLOSED with
  `close_reason="stop_loss"` (Deal field + migration `0006`). The execution has
  to be correlated to the deal — via the broker-returned identifier or via a
  position reconciliation together with `GetStopOrders`. If correlation is not
  possible → bot ERROR, no silent continuation.
- **Reading stops (B1)**: `GetStopOrders` is requested with
  `status=STOP_ORDER_STATUS_ALL` and `from`/`to` bounds (window from the deal's
  opening to now) — per the official `StopOrdersService/GetStopOrders` contract
  an explicit status filter is required to see executed/cancelled/expired
  orders, without it only ACTIVE orders are returned. A placement the broker
  did not acknowledge with a stop order id is reported `UNKNOWN` → bot ERROR
  (B3).
- **A missing stop order is an unknown state**: before any re-placement the
  broker position is reconciled (`get_open_positions` / `GetPortfolio`), not
  only `PositionManager`. Broker position zero → the close cannot be correlated
  → bot ERROR, no new stop is placed on an empty position (E2). A real broker
  position and an assembled grid → place once after the successful
  reconciliation — this applies to both the live path (`check_stop_orders`)
  and recovery (D5).
- **Recovery (D5)**: the deal's stop orders are reconciled with the broker.
  ACTIVE stays. EXECUTED → close the deal as above. Missing with the grid
  assembled → position reconciliation first, then place once. UNKNOWN → ERROR.

### E3. What the bot does after the stop — strategy setting

- `StopLossConfig.stop_bot_after: bool | None = None`. `None` is rejected at
  START (HTTP 409) for live trading — the default is not invented.
- `true` → after the stop close the bot goes to **STOPPED** via the standard
  MVP-6.5 stop; the reason is visible in the API (`stop_reason="stop-loss"`).
  A failure of that stop callback is never swallowed: the bot goes to ERROR
  through the B2 path, the reason stays observable (B2).
- `false` → the bot keeps running and waits for the next FLAT entry (new
  deposit per C6).

### E4. What is allowed in live trading

- `validate_live_deal_config()` (D1) now accepts `ExitConfig.stop_loss`
  (simple, `kind="percent"`) together with a simple TP and a «Простой»/«Свой»
  grid.
- `signal_stop`, multi-take, break-even, signal TP, trailing, and the «Сигнал»
  mode are still rejected at START.

### E5. Backtest — the same semantics

The backtest simple stop is computed with the **same E1 formula** (shared
function) and arms only after all grid levels are filled; execution is market
on the next bar (as before).

### Implementation notes

- Live: the `DealManager` stop lifecycle follows the D4 TP re-arm pattern
  (arm / re-arm / cancel / confirm / execute / recover); `check_stop_orders`
  is isolated per B1. `close_reason` is persisted via migration `0006` both
  for `take_profit` (full TP close) and `stop_loss`.
- The E1 level math lives in one place (`simple_stop_level` +
  `stop_distance_percent` in the exit engine) and is shared by Live and
  Backtest.
- Tests: `backend/tests/test_mvp616_stop_loss.py` (E1–E5, D5) plus
  `TInvestAdapter` stop-mapping tests in `tests/test_tinvest_adapter.py` and
  the E5 grid regression in `tests/test_exit_integration.py`.
