# Veles-MOEX — Architecture & Product Specification v1.0

## 1. Goal

Create a web platform for algorithmic trading of MOEX instruments through T-Invest, functionally comparable to Veles, but adapted to the Russian market.

T-Invest is the single broker integration in the MVP. The application must support both documented T-Invest connection transports — Open API and T-Invest MCP — as alternative transports for the same broker. Choosing MCP does not introduce a second broker or a second trading model.

Direct MOEX APIs (ASTS/FIX/TWIME) are not used initially.

## 2. Architecture

Browser/Web UI → REST/WebSocket → FastAPI → Strategy Engine / Backtest Engine / Trading Engine → Order Manager → Position Manager → Risk Manager → Broker Adapter → selected T-Invest transport (Open API or MCP) → MOEX.

Infrastructure:
- PostgreSQL — persistent data
- Redis — cache / queue / events
- Docker — environment
- Git/GitHub — source control

Initial architecture: modular monolith. No microservices.

## 3. Strategy Engine

A strategy is configuration/data, not user-written Python code.

Main blocks:
- Instrument
- Direction
- Entry
- DCA
- Grid
- Exit
- Risk
- Advanced

### 3.1 Veles-compatible strategy model

Veles Help Center is the functional and terminology reference. The strategy model must reproduce Veles behavior where the feature exists in Veles; MOEX/T-Invest differences are adapted only where technically necessary.

The user-facing Entry model is based on Veles-style **Filters / Signals**, not on a generic arbitrary expression tree.

A Veles-style comparison Filter has:
- Argument 1
- Operator
- Argument 2

Arguments may represent:
- templates
- configurable indicators
- signals
- TradingView sources
- partner signals
- constants

A Signal Filter is a distinct form of condition and does not have to be represented as a generic left/operator/right comparison.

### 3.2 Operators and signal semantics

Operators must preserve the distinction documented by Veles:
- greater than
- less than
- crossing upward
- crossing downward

Relational operators such as greater/less remain active while the condition is true.

Crossing operators represent an event at the crossing, rather than a persistent state.

### 3.3 Filter groups

The user-facing Veles grouping model is:
- conditions inside one group are combined with **AND / И**
- groups are combined with **OR / ИЛИ**

For example:

(A AND B) OR C

Do not replace this user-facing model with arbitrary nested AND/OR/NOT expression trees.

Internal implementation may use an evaluator abstraction, but the persisted strategy model and UI must preserve the Veles-style Filter/Group structure and semantics.

### 3.4 Timeframe and calculation method

Each indicator/filter argument may have its own timeframe/interval and supported configuration such as period, method and shift.

Entry evaluation must support the Veles-style calculation methods:
- **At bar close** — evaluate using the closed candle; a condition met at close can trigger action on the next candle.
- **Once per minute** — evaluate inside the current candle once per minute.

Multi-timeframe signal state must be preserved. A higher-timeframe signal can remain active during its timeframe interval and combine with a lower-timeframe signal when the configured conditions match.

This stateful signal behavior is part of the Strategy Engine and must not be reduced to a stateless evaluation of only the current candle.

### 3.5 Initial indicator modules

Initial indicator modules:
- RSI
- SMA
- EMA
- MACD
- Bollinger Bands
- ATR
- CCI
- Williams %R
- CMO
- MFI
- Stochastic
- ADX

The indicator library must be extensible without changing the Strategy Engine.

## 4. Entry Engine

Entry Engine evaluates opening Filters / Signals according to the Veles-compatible model above and produces trading signals.

It does not send broker orders.

The Entry Engine must preserve:
- filter arguments
- operators
- filter groups
- calculation method
- timeframe
- shift
- persistent higher-timeframe signal state
- Long / Short direction

## 5. DCA / Grid Engine

Supports:
- Initial Order
- DCA Orders
- number of levels
- spacing
- fixed distribution
- Martingale
- logarithmic distribution
- Pull-up / grid adjustment
- grid recalculation after averaging

## 6. Exit Engine

Exit Engine is a first-class subsystem.

Components:
- FixedPercentageTP
- MultiTakeTP
- SignalTP
- BreakEvenProtection
- StopLoss
- TrailingExit (future/conditional)

### Fixed TP

One exit limit order calculated from the average position price.

After DCA:
old TP → cancel → recalculate average price → create new TP with updated price and volume.

### Multi-Take

Partial exits at several profit levels.

Each take contains:
- Offset % — profit level from average entry price
- Volume % — portion of position closed

After DCA, the take-profit grid is recalculated.

### Signal TP

Closes the position when a configured indicator/filter generates a signal.

Supports Minimum P&L, which can prevent an exit before the configured minimum result.

Signal exits use market execution.

### Break-Even Protection

A separate profit-protection mechanism available with Multi-Take.

Supports reference to:
- average position price, or
- previous take-profit level

and positive, zero, or negative deviation.

After the first take, the DCA grid is cancelled and the protection stop is maintained according to the selected rule.

This is not the ordinary loss-limiting Stop Loss.

### Stop Loss

Separate protective exit mechanism.

### Trailing Exit

Interface should be designed for future implementation. Actual support for MOEX/T-Invest must be verified before implementation.

## 7. Order Manager

Order lifecycle:
- NEW
- SUBMITTED
- PARTIALLY_FILLED
- FILLED
- CANCELLED
- REJECTED
- EXPIRED
- ERROR

Responsibilities:
- create
- modify
- cancel
- execution tracking
- partial fills
- recovery
- synchronization with broker

## 8. Position Manager

Stores:
- quantity
- average_price
- realized_pnl
- unrealized_pnl
- fees
- opened_at
- duration

Average price is recalculated automatically after DCA.

## 9. Risk Manager

Separate from the strategy.

Controls:
- maximum position size
- available capital
- risk limits
- number of simultaneous bots
- instrument limits
- daily limits
- emergency stop

The strategy cannot bypass Risk Manager.

## 10. Broker Adapter

T-Invest is the **single broker** in MVP. Open API and MCP are two transports of that one broker connection.

Use the abstraction:

BrokerAdapter
├── TInvestAdapter      → T-Invest Open API
└── TInvestMcpAdapter   → T-Invest MCP

A transport/factory selected by user configuration chooses one implementation at runtime. Strategy Engine, Backtest Engine, Trading Engine, Order Manager, Position Manager and Risk Manager must not depend on the selected transport.

Both adapters must expose the same broker-agnostic DTOs and order lifecycle. MCP-specific protocol objects must not leave the broker integration layer.

The current read-only implementation remains `TInvestAdapter` over Open API. `TInvestMcpAdapter` is an explicit integration boundary to be implemented before MCP is exposed as an executable user option. This avoids pretending that MCP support is already production-ready while preserving the architecture for both transports.

Official T-Invest MCP endpoint: `https://invest-public-api.tbank.ru/mcp`. T-Bank documents HTTP Streamable transport and Bearer authentication for it.

## 11. Backtest Engine

Backtest and Live use the same Strategy/Trading Engine.

Live:
Trading Engine → BrokerAdapter → selected T-Invest transport (Open API or MCP)

Backtest:
Trading Engine → BacktestBroker

Backtest must model:
- commissions
- order types
- partial fills
- DCA
- TP
- Multi-Take
- Signal TP
- Stop Loss
- Break-Even
- slippage
- quantity/lot/tick constraints
- trading sessions
- instrument-specific rules

## 12. Market Data Layer

Supports:
- OHLCV
- timeframes
- trades
- quotes
- T-Invest market data
- historical data for backtesting

The data model must support MOEX-specific properties:
- lot size
- tick size
- trading sessions
- clearing periods
- different trading modes

## 13. Database

Core entities:
- users
- accounts
- brokers
- instruments
- strategies
- strategy_versions
- bots
- orders
- executions
- positions
- deals
- market_data
- signals
- events
- backtests
- backtest_trades

Strategy versions are immutable references for historical backtests.

## 14. Web UI

Main sections:
- Dashboard
- Strategies
- Backtests
- Bots
- Positions
- Orders
- Deals
- Instruments
- Statistics
- Settings

Strategy page:
Instrument / Direction / Entry / DCA / Grid / Exit / Risk / Advanced

Actions:
- Backtest
- Save
- Start
- Stop

Paper Trading is not part of MVP.

## 15. Backtest UI

Inputs:
- instrument
- period
- timeframe
- initial capital
- commission
- slippage
- strategy

Outputs:
- Net P&L
- Gross P&L
- ROI
- CAGR
- Maximum Drawdown
- Recovery
- MAE
- number of trades
- Win Rate
- average trade
- average duration
- commission

Charts:
- Equity Curve
- Drawdown
- Trades
- Price + Entries/Exits
- Position Size

## 16. MVP Roadmap

### MVP-1 — Broker & Market Data
- T-Invest connection (single broker; user-selectable Open API or MCP transport)
- account
- instruments
- market data
- positions
- orders
- deals
- basic Web UI

### MVP-2 — Strategy Engine
- Veles-compatible Entry model
- Veles-style Filters / Signals
- Filter arguments
- comparison operators and crossing operators
- Filter Groups: AND inside group, OR between groups
- calculation methods: bar close / once per minute
- timeframe and shift
- multi-timeframe signal state
- basic indicators
- Long / Short
- basic Exit

### MVP-3 — Backtest
- historical data
- BacktestBroker
- commissions
- slippage
- statistics
- charts

### MVP-4 — DCA / Grid
- averaging
- grid
- Martingale
- logarithmic distribution
- position/grid recalculation

### MVP-5 — Full Exit Engine
- Fixed TP
- Multi-Take
- Signal TP
- Minimum P&L
- Break-Even Protection
- Stop Loss

### MVP-6 — Live Trading
- bot start/stop
- Order Manager
- Risk Manager
- recovery
- reconnect
- emergency stop

## 17. Post-MVP

Potential later features:
- Trailing
- additional indicators
- optimizer
- Indicator Selection
- advanced statistics
- additional brokers
- Paper Trading, only if practical need is demonstrated

## 18. Explicitly Out of Initial Scope

- Direct MOEX API
- ASTS/FIX/TWIME
- microservices
- mobile application
- HFT
- multiple brokers (T-Invest remains the single MVP broker)
- AI strategy generator
- strategy optimizer
- huge indicator library
- Paper Trading

## 19. Development Principles

1. Trading-core correctness before UI polish.
2. Backtest and Live must share the same trading logic.
3. Broker-specific logic stays inside the Broker Adapter.
4. Historical strategy versions must remain reproducible.
5. Financial parameters are not tuned autonomously by the coding agent.
6. Architecture decisions are made before implementation tasks are delegated to OpenCode.
7. **Veles Help Center is the functional and terminology reference. The Veles user model is reproduced first; MOEX/T-Invest constraints determine only the required adaptations.**
8. **Do not introduce a generic trading-rule abstraction when Veles already defines the corresponding user-facing behavior.**
9. **Before implementing any new strategy feature, verify its Veles behavior against the current Veles Help Center.**
