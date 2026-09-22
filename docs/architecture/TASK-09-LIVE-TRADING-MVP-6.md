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

