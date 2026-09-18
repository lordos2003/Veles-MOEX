# Veles Help Center — reference for MOEX Veles-like project

Source: https://help.veles.finance/ru/
Reviewed: 2026-09-18
Purpose: engineering reference for building a Veles-like algorithmic trading platform for MOEX using T-Invest API.

## Core platform model
- Veles bot automates entry, averaging, profit-taking and exits via exchange API.
- Supports single-order trading and DCA/grid averaging.
- Direction: Long or Short; no neutral mode.
- Entry can be unconditional or based on filters/indicators.
- Exit can use fixed profit, multiple partial exits, indicators/signals, price filters, or stop-loss.
- DCA can be manually configured or generated with order count, overlap, martingale, first-order offset and logarithmic distribution.
- Signal mode uses market orders when conditions fire; limit/grid modes expose orders in advance.

## Bot configuration concepts to reproduce
- API binding / broker connection
- Trading type
- Instrument / trading pair
- Bot deposit
- Indicative account balance
- Leverage
- Margin type: isolated / cross
- Reinvestment
- Trading mode: Simple / Custom / Signal
- Price-change overlap (range between first and last grid order)
- Grid order count
- Martingale percentage
- First-order offset
- Logarithmic price distribution
- Partial grid placement
- Grid pull-up / refresh
- Stop bot after N deals
- Include existing exchange position in deal
- Entry conditions
- Take-profit mode: Simple / Custom / Signal
- Stop-loss
- Backtest
- TradingView preview

Important semantics from Veles docs:
- Higher % overlap means wider grid coverage.
- More grid orders divide the position into more orders.
- Martingale increases the size of subsequent orders and pulls average entry closer to current price.
- Logarithm > 1 makes orders denser near current price; < 1 makes them denser farther away; off = uniform spacing.
- First-order offset: Long below current price; Short above current price.
- Signal mode uses market execution at signal time.
- Grid/limit modes can have orders visible on the exchange before execution.
- Editing an active bot applies new settings from the next deal; cloning is recommended for safe experimentation.

## Filter engine
Filters/indicators determine whether to open, average or close a deal.
Multiple filters require signal matching; evaluation is described as higher timeframes to lower timeframes. A higher-TF signal can remain active until that candle interval ends and combine with a lower-TF signal.

Two calculation methods:
1. At bar close: calculate on a closed candle; a condition met at close leads to action on the next candle.
2. Once per minute: evaluate inside the candle every minute. Veles notes this is mainly suitable for channel/price-change indicators and is difficult to reproduce exactly for support/debugging.

Flexible indicators:
- Each condition consists of Argument 1 + Operator + Argument 2.
- Arguments can be templates, configurable indicators, signals, TradingView, partner signals, or constants.
- Groups: conditions inside one group = AND; groups = OR.
- Allows comparing indicator vs indicator, custom periods/lengths, timeframe, method and shift.
- Candle provides Open/Close/High/Low/Volume and shift.
- Operators differ materially: >/< remain active while condition holds; crossing operators fire at the crossing event.

## Indicator catalog reviewed
- Three Candles
- ADX
- ALMA
- ATR
- Awesome Oscillator
- Bollinger Bands
- Balance of Power
- Candle
- Candles Trend
- CCI
- Chaikin Oscillator
- CMO
- Connors RSI
- Donchian Channel
- Ehlers SuperSmoother
- EMA
- HMA
- Hull Volume MA
- Ichimoku Cloud
- Keltner Channel
- Liquidation Heatmap
- LSMA
- MACD
- MFI
- Mean Reversion Channel (MRC)
- Percentage Price Change
- Price Filter
- Parabolic SAR
- Rate of Change
- RSI
- RVI
- SMA
- SMMA
- SrgArt DiverX
- Stochastic RSI
- Stochastic
- SuperTrend
- Turtle Zone
- Volume Filter
- Volume Spike Detector
- Vortex Indicator
- VuManChu Cipher B + Divergences
- VWMA
- Williams %R
- WMA
- plus TradingView, subscription signals, schedule and constant filters.

## Important indicator-specific principles
- RSI default period is 14; flexible mode exposes period, interval, method and shift.
- Bollinger/other channels can be represented as comparisons between Candle Close and channel boundaries.
- Candle Close is the direct price source in flexible conditions.
- Volume can be base-asset volume or nominal/quote volume.
- Price Filter is effectively a threshold condition and can be used with Minimum PnL for dynamic exits.
- MRC is available as a Veles filter and is relevant to mean-reversion strategies.
- Stochastic and StochRSI expose crossing and overbought/oversold logic.

## Risk management principles from Veles documentation
- Backtest before live trading.
- Evaluate long historical periods and strong drawdowns, not only short favorable windows.
- For cross margin without stop-loss, Veles recommends determining Maximum Floating Loss (MFL/МПУ) from a long backtest and maintaining a large margin reserve.
- Veles warns that short grids / small overlap can produce deceptively good results through over-optimization.
- Lower leverage reduces MFL; increasing overlap and martingale can also reduce MFL in their grid model, while logarithmic distribution changes where orders concentrate.
- Entry filters can reduce poor entries but do not guarantee protection from large moves.
- Backtests should be checked for net profit, MFL, open/unclosed deals, duration and other weaknesses.

## Backtesting principles
- Backtest is a simulation on historical data.
- Veles documentation emphasizes checking Net profit, MFL, drawdown, long-running/open deals, and individual deal behavior.
- Indicator auto-selection is a discovery tool, not a final strategy; its results are based on a limited recent candle window and must be validated with longer backtests and across assets/periods.

## UI/product concepts worth reproducing in MOEX project
- Dashboard
- Strategy/bot cards with status
- Strategy editor
- Active deal card
- Deal management
- Trading statistics
- Backtest history and result pages
- Instrument chart with planned orders/grid
- Signal preview: calculate/show signals
- Preset/template strategies
- Clone strategy for safe experiments
- Notifications
- API/broker connections
- Risk locks / safety controls
- Terminal with widgets and trading view

## Translation into our MOEX project
The Veles documentation is a product/behavior reference, not a source of crypto-specific implementation details. We should reproduce the useful abstractions while adapting them to MOEX and T-Invest:
- ExchangeAdapter -> TInvestAdapter
- MarketDataProvider
- Strategy Engine
- Indicator Engine
- Signal Engine
- DCA/Grid Engine
- Order Manager
- Position Manager
- Risk Manager
- Backtest Engine + Virtual Broker
- Paper Trading Broker
- Live Broker
- FastAPI backend
- PostgreSQL persistence
- WebSocket real-time updates
- React/TypeScript web frontend

Critical design rule: the strategy engine must not know about T-Invest. Backtest, paper and live modes should use the same strategy logic and different broker/execution adapters.

## Documentation navigation observed
The Russian Veles Help Center is organized into:
- Getting started / platform overview
- Pricing and fees
- Education/support/glossary
- Beginner guide / FAQ / mistakes / troubleshooting
- Strategies and risk management
- Exchange/API connection
- Platform/dashboard
- Bot settings and management
- Filters and indicators
- Terminal

This reference intentionally summarizes the documentation rather than reproducing the full copyrighted articles. When an implementation question depends on exact Veles behavior, consult the current official article at the source URL and verify the behavior before coding it.
