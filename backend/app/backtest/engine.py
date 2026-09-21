"""Backtest Engine.

Backtest reuses the same Strategy Engine as Live, but drives execution through
|BacktestBroker| instead of a live broker adapter (Architecture & Product
Specification section 11). The engine steps through chronological historical
candles; the Strategy Engine never knows it is a backtest.

Timing (Veles): a signal formed on bar N close executes at bar N+1 open. Only
``at_bar_close`` is supported; ``per_minute`` is out of scope for MVP-3. No
future data is used to compute a signal.

The result is fully deterministic given a |BacktestConfig|.
"""

from __future__ import annotations

from decimal import Decimal

from app.backtest.broker import BacktestBroker
from app.backtest.config import BacktestConfig
from app.backtest.models import BacktestDeal, BacktestResult
from app.domain.marketdata import Candle
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import Direction
from app.strategies.domain import MarketContext
from app.trading.engine import TradingEngine


class BacktestEngine:
    """Runs a strategy over historical data via the shared Strategy Engine."""

    def __init__(self, trading_engine: TradingEngine) -> None:
        # The injected Trading Engine must be wired to a BacktestBroker; only its
        # factory Strategy Engine is used to produce signals, so Live and
        # Backtest share the exact same trading logic.
        self.trading_engine = trading_engine

    @property
    def _strategy(self):
        return self.trading_engine.strategy_engine

    def run(self, config: BacktestConfig) -> BacktestResult:
        candles = sorted(config.candles, key=lambda c: c.timestamp)
        if not candles:
            return self._empty_result(config)

        direction = config.strategy.direction
        broker = BacktestBroker(
            account_id=config.account_id,
            initial_capital=config.initial_capital,
            maker_fee=config.maker_fee,
            taker_fee=config.taker_fee,
            slippage=config.slippage,
            figi=config.instrument_figi,
            candles=candles,
        )

        bar_series = BarSeries(timeframe=config.timeframe, bars=[])
        deals: list[BacktestDeal] = []
        equity_curve: list[Decimal] = []

        pending_entry = None
        entry_fill = None
        tp_order_id: str | None = None

        for candle in candles:
            # (A) Execute a market entry signalled on the previous bar's close.
            if pending_entry is not None and not broker.is_open():
                side = pending_entry.direction
                qty = config.quantity
                broker.execute_market(
                    side, qty, price=Decimal(candle.open), timestamp=candle.timestamp
                )
                fills = broker.deals()
                entry_fill = fills[-1] if fills else None
                pending_entry = None
                # (B) compute TP from the actual average price and arm it as a limit.
                self._arm_take_profit(broker, config, direction, qty, candle)
                tp_order_id = self._last_tp_order_id

            # (C) Fill pending limit (the take-profit) using the current bar.
            for deal in broker.on_bar(candle):
                if deal.order_id == tp_order_id and not broker.is_open() and entry_fill is not None:
                    deals.append(self._build_deal(entry_fill, deal, direction, len(deals) + 1))
                    entry_fill = None
                    tp_order_id = None

            # (D) Evaluate the strategy at this bar's close (no future data).
            bar_series.bars.append(self._to_bar(candle))
            context = MarketContext(
                snapshot=Snapshot(series={config.timeframe: bar_series}),
                timestamp=candle.timestamp,
                price=float(candle.close),
            )
            plan = self._strategy.evaluate(config.strategy, context)
            if plan.entry is not None and not broker.is_open():
                pending_entry = plan.entry

            # (E) Mark to market for the equity curve.
            broker.set_price(Decimal(candle.close))
            equity_curve.append(broker.equity())

        return self._build_result(
            config, broker, direction, deals, equity_curve, entry_fill
        )

    def _arm_take_profit(
        self,
        broker: BacktestBroker,
        config: BacktestConfig,
        direction: Direction,
        qty: Decimal,
        candle: Candle,
    ) -> None:
        avg = broker.average_price()
        plans = self._strategy.exit_engine.build_exit_orders(
            config.strategy.exit, direction, avg, qty
        )
        self._last_tp_order_id = None
        if plans and plans[0].price is not None:
            order = broker.place_limit(
                plans[0].side, qty, plans[0].price, timestamp=candle.timestamp
            )
            self._last_tp_order_id = order.order_id

    @staticmethod
    def _build_deal(entry_fill, exit_fill, direction: Direction, seq: int) -> BacktestDeal:
        exit_price = exit_fill.price
        entry_price = entry_fill.price
        qty = entry_fill.quantity
        if direction == Direction.SHORT:
            gross = (entry_price - exit_price) * qty
        else:
            gross = (exit_price - entry_price) * qty
        fees = entry_fill.commission + exit_fill.commission
        net = gross - fees
        exit_time = exit_fill.happened_at
        entry_time = entry_fill.happened_at
        return BacktestDeal(
            deal_id=f"trade-{seq}",
            direction=direction,
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=qty,
            gross_pnl=gross,
            fees=fees,
            net_pnl=net,
            duration=exit_time - entry_time,
            executed_orders=2,
        )

    @staticmethod
    def _to_bar(candle: Candle) -> Bar:
        return Bar(
            timestamp=candle.timestamp,
            open=float(candle.open),
            high=float(candle.high),
            low=float(candle.low),
            close=float(candle.close),
            volume=float(candle.volume),
            is_complete=True,
        )

    @staticmethod
    def _empty_result(config: BacktestConfig) -> BacktestResult:
        return BacktestResult(
            initial_capital=config.initial_capital,
            final_capital=config.initial_capital,
            gross_pnl=Decimal("0"),
            net_pnl=Decimal("0"),
            roi=Decimal("0"),
            total_fees=Decimal("0"),
            num_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=Decimal("0"),
            average_trade=Decimal("0"),
            average_duration=Decimal("0"),
            max_drawdown=Decimal("0"),
        )

    @staticmethod
    def _build_result(config, broker, direction, deals, equity_curve, entry_fill) -> BacktestResult:
        gross = sum((d.gross_pnl for d in deals), Decimal("0"))
        net = sum((d.net_pnl for d in deals), Decimal("0"))
        fees = sum((d.fees for d in deals), Decimal("0"))
        num = len(deals)
        winning = sum(1 for d in deals if d.is_win)
        losing = num - winning
        win_rate = Decimal(str(winning / num)) if num else Decimal("0")
        avg_trade = net / num if num else Decimal("0")
        if num:
            secs = sum(d.duration.total_seconds() for d in deals) / num
            avg_duration = Decimal(str(secs))
        else:
            avg_duration = Decimal("0")
        max_dd = max_drawdown(equity_curve)
        final_capital = broker.equity()
        roi = (net / config.initial_capital) if config.initial_capital else Decimal("0")
        return BacktestResult(
            initial_capital=config.initial_capital,
            final_capital=final_capital,
            gross_pnl=gross,
            net_pnl=net,
            roi=roi,
            total_fees=fees,
            num_trades=num,
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            average_trade=avg_trade,
            average_duration=avg_duration,
            max_drawdown=max_dd,
            deals=deals,
            orders=broker.orders(),
            executions=broker.deals(),
        )


def max_drawdown(equity_curve: list[Decimal]) -> Decimal:
    """Return the maximum peak-to-trough decline as a fraction of the peak."""
    peak = Decimal("0")
    max_dd = Decimal("0")
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd
