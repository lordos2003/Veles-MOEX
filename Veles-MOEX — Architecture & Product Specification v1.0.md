# Veles-MOEX — Architecture & Product Specification v1.0

## 1. Goal

Create a web platform for algorithmic trading of MOEX instruments through T-Invest API, functionally comparable to Veles, but adapted to the Russian market.

Direct MOEX APIs (ASTS/FIX/TWIME) are not used initially.

## 2. Architecture

Browser/Web UI → REST/WebSocket → FastAPI → Strategy Engine / Backtest Engine / Trading Engine → Order Manager → Position Manager → Risk Manager → Broker Adapter → TInvest Adapter → T-Invest API → MOEX.

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

Condition logic:
- AND
- OR
- NOT
- nested groups

Initial indicator modules:
RSI, SMA, EMA, MACD, Bollinger Bands, ATR, CCI, Williams %R, CMO, MFI, Stochastic, ADX.

The indicator library must be extensible without changing the Strategy Engine.

## 4. Entry Engine

Entry Engine evaluates opening conditions and produces trading signals.

It does not send broker orders.

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

Use an abstraction:

BrokerAdapter → TInvestAdapter

Strategy Engine must not depend on T-Invest specifics.

This allows additional brokers later without rewriting strategies.

## 11. Backtest Engine

Backtest and Live use the same Strategy/Trading Engine.

Live:
Trading Engine → TInvestAdapter

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
- T-Invest connection
- account
- instruments
- market data
- positions
- orders
- deals
- basic Web UI

### MVP-2 — Strategy Engine
- Entry
- basic indicators
- conditions
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
- multiple brokers
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
7. Veles Help Center is the functional and terminology reference; MOEX/T-Invest constraints determine the implementation details.
