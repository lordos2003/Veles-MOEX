"""Backtest Engine.

Backtest reuses the same Strategy Engine as Live, but drives execution through
|BacktestBroker| instead of a live broker adapter (Architecture & Product
Specification section 11). The engine steps through chronological historical
candles; the Strategy Engine never knows it is a backtest.

Timing (Veles): a signal formed on bar N close executes at bar N+1 open. Only
``at_bar_close`` is supported; ``per_minute`` is out of scope. No future data is
used to compute a signal.

DCA / Grid (MVP-4): after the initial market entry, SIMPLE and CUSTOM grids are
armed as deterministic limit orders. A DCA level fills via the existing OHLC
limit rule, the position is averaged (weighted), grid state advances and the
take-profit limit is re-armed from the new average price. SIGNAL-mode averaging
is exercised at the engine level only (market DCA on signals is not simulated
in the bar loop here).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.backtest.broker import BacktestBroker
from app.backtest.config import BacktestConfig
from app.backtest.models import BacktestDeal, BacktestResult
from app.domain.marketdata import Candle
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import Direction, TradingMode
from app.strategies.dca_grid import DCAGridEngine, GridState
from app.strategies.domain import MarketContext
from app.trading.engine import TradingEngine


class BacktestEngine:
    """Runs a strategy over historical data via the shared Strategy Engine."""

    def __init__(self, trading_engine: TradingEngine) -> None:
        self.trading_engine = trading_engine
        self._grid_engine = DCAGridEngine()

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
        tp_order_id: str | None = None
        grid_state: GridState | None = None
        dca_order_ids: dict[int, str] = {}

        # Position bookkeeping for the current trade.
        entry_fill = None
        pos_qty = Decimal("0")
        pos_avg = Decimal("0")
        pos_entry_time: datetime | None = None
        pos_fees = Decimal("0")
        pos_fill_count = 0

        for candle in candles:
            # (A) Execute a market entry signalled on the previous bar's close.
            if pending_entry is not None and not broker.is_open():
                qty = config.quantity
                broker.execute_market(
                    pending_entry.direction,
                    qty,
                    price=Decimal(candle.open),
                    timestamp=candle.timestamp,
                )
                entry_fill = broker.deals()[-1] if broker.deals() else None
                pending_entry = None
                pos_qty = qty
                pos_avg = broker.average_price()
                pos_entry_time = candle.timestamp
                pos_fees = entry_fill.commission if entry_fill else Decimal("0")
                pos_fill_count = 1
                tp_order_id = self._place_take_profit(broker, config, direction, candle, None)
                grid_state, dca_order_ids = self._init_grid(
                    broker, config, direction, candle
                )

            # (C) Fill pending limit orders (DCA levels and take-profit).
            for deal in broker.on_bar(candle):
                if deal.order_id == tp_order_id and not broker.is_open() and entry_fill is not None:
                    deals.append(
                        self._build_deal(
                            deal,
                            direction,
                            pos_avg,
                            pos_qty,
                            pos_entry_time,
                            pos_fees + deal.commission,
                            pos_fill_count + 1,
                            len(deals) + 1,
                        )
                    )
                    entry_fill = None
                    tp_order_id = None
                    grid_state = None
                    dca_order_ids = {}
                elif grid_state is not None:
                    idx = self._match_dca_level(dca_order_ids, deal.order_id)
                    if idx is not None:
                        self._on_dca_fill(broker, grid_state, idx, dca_order_ids, config, candle)
                        pos_avg = broker.average_price()
                        pos_qty = abs(broker.position_quantity())
                        pos_fees += deal.commission
                        pos_fill_count += 1
                        tp_order_id = self._place_take_profit(
                            broker, config, direction, candle, tp_order_id
                        )

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

        return self._build_result(config, broker, direction, deals, equity_curve)

    def _init_grid(self, broker, config, direction, candle):
        """Build the grid after the initial entry; arm active limit DCA levels."""
        dca = config.strategy.dca_grid
        if dca.mode not in (TradingMode.SIMPLE, TradingMode.CUSTOM):
            return None, {}
        if dca.mode == TradingMode.SIMPLE and dca.levels <= 1:
            return None, {}
        if dca.mode == TradingMode.CUSTOM and not dca.custom_levels:
            return None, {}

        reference = broker.average_price()
        base_nominal = abs(broker.position_quantity()) * reference
        state = self._grid_engine.build(dca, reference, direction, base_nominal=base_nominal)
        state.average_price = reference
        self._grid_engine.on_fill(state, 0)
        orders: dict[int, str] = {}
        self._place_dca_orders(broker, state, orders, candle)
        return state, orders

    def _place_dca_orders(self, broker, state: GridState, orders: dict[int, str], candle) -> None:
        for plan in state.active_orders():
            if plan.is_market or plan.level_index in orders or plan.price is None:
                continue
            order = broker.place_limit(
                plan.side, plan.quantity, plan.price, timestamp=candle.timestamp
            )
            orders[plan.level_index] = order.order_id

    @staticmethod
    def _match_dca_level(dca_order_ids: dict[int, str], order_id: str) -> int | None:
        for idx, oid in dca_order_ids.items():
            if oid == order_id:
                return idx
        return None

    def _on_dca_fill(
        self, broker, state: GridState, idx: int, dca_order_ids: dict[int, str], config, candle
    ) -> None:
        self._grid_engine.on_fill(state, idx)
        state.average_price = broker.average_price()
        self._place_dca_orders(broker, state, dca_order_ids, candle)

    def _place_take_profit(self, broker, config, direction, candle, previous_order_id):
        if previous_order_id is not None:
            broker.cancel(previous_order_id)
        avg = broker.average_price()
        qty = abs(broker.position_quantity())
        plans = self._strategy.exit_engine.build_exit_orders(
            config.strategy.exit, direction, avg, qty
        )
        if plans and plans[0].price is not None:
            order = broker.place_limit(
                plans[0].side, qty, plans[0].price, timestamp=candle.timestamp
            )
            return order.order_id
        return None

    @staticmethod
    def _build_deal(
        exit_fill, direction, entry_price, quantity, entry_time, fees, executed_orders, seq
    ) -> BacktestDeal:
        exit_price = exit_fill.price
        if direction == Direction.SHORT:
            gross = (entry_price - exit_price) * quantity
        else:
            gross = (exit_price - entry_price) * quantity
        net = gross - fees
        return BacktestDeal(
            deal_id=f"trade-{seq}",
            direction=direction,
            entry_time=entry_time,
            exit_time=exit_fill.happened_at,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            gross_pnl=gross,
            fees=fees,
            net_pnl=net,
            duration=exit_fill.happened_at - entry_time,
            executed_orders=executed_orders,
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
    def _build_result(config, broker, direction, deals, equity_curve) -> BacktestResult:
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
