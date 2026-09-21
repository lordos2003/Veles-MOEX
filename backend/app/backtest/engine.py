"""Backtest Engine.

Backtest reuses the same Strategy Engine as Live, but drives execution through
|BacktestBroker| instead of a live broker adapter (Architecture & Product
Specification section 11). The engine steps through chronological historical
candles; the Strategy Engine never knows it is a backtest.

Timing (Veles): a signal formed on bar N close executes at bar N+1 open. Only
``at_bar_close`` is supported; ``per_minute`` is out of scope. No future data is
used.

Exits (MVP-5): Fixed TP / Multi-Take are placed as deterministic limit orders;
Signal TP / Simple Stop Loss / Signal Stop Loss / Break-Even are market exits
evaluated at bar close and executed at the next bar open. Multiple simultaneous
exits are resolved by the ExitEngine's deterministic priority.
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
from app.strategies.exit import ExitDecision, ExitEngine, ExitState
from app.strategies.filters import CalculationMethod, FilterEvaluator
from app.trading.engine import TradingEngine


class BacktestEngine:
    """Runs a strategy over historical data via the shared Strategy Engine."""

    def __init__(self, trading_engine: TradingEngine) -> None:
        self.trading_engine = trading_engine
        self._grid_engine = DCAGridEngine()
        self._filter_eval = FilterEvaluator()
        self._exit_engine: ExitEngine = self._strategy.exit_engine

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
        pending_market_exit: ExitDecision | None = None
        grid_state: GridState | None = None
        dca_order_ids: dict[int, str] = {}
        exit_state = ExitState(
            mode=self._exit_engine.resolve_mode(config.strategy.exit), direction=direction
        )
        limit_orders: dict[str, tuple[str, int]] = {}

        entry_fill = None
        pos_qty = Decimal("0")
        pos_avg = Decimal("0")
        pos_entry_time: datetime | None = None
        pos_gross = Decimal("0")
        pos_fees = Decimal("0")
        pos_fill_count = 0
        pos_added_qty = Decimal("0")

        for candle in candles:
            # (A) Execute pending market entry on this bar's open.
            if pending_entry is not None and not broker.is_open():
                qty = config.quantity
                broker.execute_market(
                    pending_entry.direction, qty, price=Decimal(candle.open),
                    timestamp=candle.timestamp,
                )
                pending_entry = None
                entry_fill = broker.deals()[-1] if broker.deals() else None
                pos_qty = qty
                pos_avg = broker.average_price()
                pos_entry_time = candle.timestamp
                pos_fees = entry_fill.commission if entry_fill else Decimal("0")
                pos_gross = Decimal("0")
                pos_fill_count = 1
                pos_added_qty = qty
                exit_state = ExitState(
                    mode=self._exit_engine.resolve_mode(config.strategy.exit), direction=direction
                )
                limit_orders, grid_state, dca_order_ids = self._after_entry(
                    broker, config, direction, pos_avg, pos_qty, candle, limit_orders
                )

            # (B) Execute a pending market exit on this bar's open.
            if pending_market_exit is not None and broker.is_open():
                self._execute_market_exit(
                    broker, config, pending_market_exit, candle, deals,
                    direction, pos_avg, pos_qty, pos_entry_time,
                    pos_gross, pos_fees, pos_fill_count,
                )
                pos_qty, pos_avg, pos_entry_time = Decimal("0"), Decimal("0"), None
                pos_gross, pos_fees, pos_fill_count = Decimal("0"), Decimal("0"), 0
                entry_fill = None
                pending_market_exit = None
                limit_orders = {}
                grid_state = None
                dca_order_ids = {}
                continue

            # (C) Fill pending limit orders (DCA levels, take-profits, takes).
            for deal in broker.on_bar(candle):
                order_id = deal.order_id
                if order_id in dca_order_ids.values():
                    idx = self._match_dca_level(dca_order_ids, order_id)
                    if idx is not None and grid_state is not None:
                        self._grid_engine.on_fill(grid_state, idx)
                        grid_state.average_price = broker.average_price()
                        self._place_dca_orders(broker, grid_state, dca_order_ids, candle)
                        pos_avg = broker.average_price()
                        pos_qty = abs(broker.position_quantity())
                        pos_fees += deal.commission
                        pos_fill_count += 1
                        pos_added_qty += deal.quantity
                        self._rearm_exits(
                            broker, config, direction, pos_avg, pos_qty,
                            exit_state.executed_takes, limit_orders,
                        )
                elif order_id in limit_orders:
                    kind, take_index = limit_orders[order_id]
                    prev_avg = pos_avg
                    if kind == "take":
                        self._exit_engine.on_take_executed(
                            exit_state, config.strategy.exit, take_index, deal.price
                        )
                    pos_avg = broker.average_price()
                    pos_qty = abs(broker.position_quantity())
                    pos_fees += deal.commission
                    pos_fill_count += 1
                    pos_gross += self._realized_gross(direction, prev_avg, deal)
                    if not broker.is_open():
                        deals.append(
                            self._build_deal(
                                deal, direction, prev_avg, pos_added_qty, pos_entry_time,
                                pos_gross, pos_fees, pos_fill_count, len(deals) + 1,
                                reason=("take" if kind == "take" else "fixed_tp"),
                            )
                        )
                        pos_qty, pos_avg, pos_entry_time = Decimal("0"), Decimal("0"), None
                        pos_gross, pos_fees, pos_fill_count = Decimal("0"), Decimal("0"), 0
                        pos_added_qty = Decimal("0")
                        limit_orders = {}
                        grid_state = None
                        dca_order_ids = {}

            # (D) Append bar, evaluate strategy + market exits at close.
            bar_series.bars.append(self._to_bar(candle))
            context = MarketContext(
                snapshot=Snapshot(series={config.timeframe: bar_series}),
                timestamp=candle.timestamp,
                price=float(candle.close),
            )
            plan = self._strategy.evaluate(config.strategy, context)
            if plan.entry is not None and not broker.is_open():
                pending_entry = plan.entry

            if broker.is_open():
                pending_market_exit = self._evaluate_market_exit(
                    config, direction, pos_avg, pos_qty, exit_state,
                    bar_series, candle, context,
                )

            # (E) Mark to market.
            broker.set_price(Decimal(candle.close))
            equity_curve.append(broker.equity())

        return self._build_result(config, broker, direction, deals, equity_curve)

    # --- exit integration ---------------------------------------------------------

    def _after_entry(self, broker, config, direction, avg, qty, candle, limit_orders):
        exit_state = ExitState(
            mode=self._exit_engine.resolve_mode(config.strategy.exit), direction=direction
        )
        exit_state.average_price = avg
        exit_state.remaining_quantity = qty
        self._place_limit_exits(broker, config, direction, avg, qty, [], limit_orders)
        grid_state, dca_order_ids = self._init_grid(broker, config, direction, candle)
        return limit_orders, grid_state, dca_order_ids

    def _place_limit_exits(
        self, broker, config, direction, avg, qty, executed_takes, limit_orders
    ) -> None:
        exit_cfg = config.strategy.exit
        is_multi = exit_cfg.take_profit.kind == "multi_take"
        plans = self._exit_engine.build_remaining_take_plans(
            exit_cfg, direction, avg, qty, executed_takes
        )
        for i, plan in enumerate(plans):
            if plan.price is None:
                continue
            # Use the exact remaining quantity for a full-closure (Fixed TP) exit so
            # the position closes exactly, avoiding float residual.
            order_qty = qty if not is_multi else Decimal(str(plan.quantity))
            order = broker.place_limit(plan.side, order_qty, plan.price, timestamp=None)
            limit_orders[order.order_id] = ("take" if is_multi else "tp", i)

    def _rearm_exits(
        self, broker, config, direction, avg, qty, executed_takes, limit_orders
    ) -> None:
        self._cancel_limit_orders(broker, limit_orders)
        limit_orders.clear()
        self._place_limit_exits(broker, config, direction, avg, qty, executed_takes, limit_orders)

    def _cancel_limit_orders(self, broker, limit_orders) -> None:
        for oid in list(limit_orders.keys()):
            broker.cancel(oid)

    def _evaluate_market_exit(
        self, config, direction, avg, qty, exit_state, bar_series, candle, context
    ) -> ExitDecision | None:
        exit_cfg = config.strategy.exit
        price = Decimal(candle.close)
        now = candle.timestamp
        decisions: list[ExitDecision] = []
        tp = exit_cfg.take_profit
        if tp.kind == "signal":
            fired = self._filter_eval.evaluate(
                tp.groups, CalculationMethod.AT_BAR_CLOSE, context.snapshot, now
            )
            decision = self._exit_engine.signal_tp_decision(
                exit_cfg, direction, avg, qty, price, fired, now
            )
            if decision:
                decisions.append(decision)
        if exit_cfg.stop_loss is not None:
            decision = self._exit_engine.simple_stop_decision(
                exit_cfg, direction, avg, price, qty, now
            )
            if decision:
                decisions.append(decision)
        if exit_cfg.signal_stop is not None:
            fired = self._filter_eval.evaluate(
                exit_cfg.signal_stop.groups, CalculationMethod.AT_BAR_CLOSE, context.snapshot, now
            )
            grid_assembled = self._grid_assembled(avg)
            decision = self._exit_engine.signal_stop_decision(
                exit_cfg, direction, fired, avg, exit_state.last_take_price,
                price, qty, grid_assembled, now,
            )
            if decision:
                decisions.append(decision)
        if exit_state.breakeven_active:
            decision = self._exit_engine.breakeven_decision(
                exit_cfg, exit_state, avg, exit_state.last_take_price, price, qty, now
            )
            if decision:
                decisions.append(decision)
        return self._exit_engine.select(decisions)

    def _grid_assembled(self, avg) -> bool:
        return True

    def _execute_market_exit(
        self, broker, config, decision, candle, deals, direction,
        avg, qty, entry_time, gross, fees, fill_count,
    ) -> None:
        broker.execute_market(
            decision.side, decision.quantity, price=Decimal(candle.open), timestamp=candle.timestamp
        )
        exit_fill = broker.deals()[-1] if broker.deals() else None
        if exit_fill is None:
            return
        total_gross = gross + self._realized_gross(direction, avg, exit_fill)
        total_fees = fees + exit_fill.commission
        deals.append(
            self._build_deal(
                exit_fill, direction, avg, qty, entry_time, total_gross, total_fees,
                fill_count + 1, len(deals) + 1, reason=decision.exit_type.value,
            )
        )

    # --- DCA grid ---------------------------------------------------------------

    def _init_grid(self, broker, config, direction, candle):
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

    # --- deal / helpers ---------------------------------------------------------

    @staticmethod
    def _realized_gross(direction, avg, fill) -> Decimal:
        if fill.quantity <= 0:
            return Decimal("0")
        if direction == Direction.SHORT:
            return (avg - fill.price) * fill.quantity
        return (fill.price - avg) * fill.quantity

    @staticmethod
    def _build_deal(
        exit_fill, direction, entry_price, quantity, entry_time, gross, fees,
        executed_orders, seq, reason: str = "",
    ) -> BacktestDeal:
        return BacktestDeal(
            deal_id=f"trade-{seq}",
            direction=direction,
            entry_time=entry_time,
            exit_time=exit_fill.happened_at,
            entry_price=entry_price,
            exit_price=exit_fill.price,
            quantity=quantity,
            gross_pnl=gross,
            fees=fees,
            net_pnl=gross - fees,
            duration=exit_fill.happened_at - entry_time,
            executed_orders=executed_orders,
            reason=reason,
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
