"""Deterministic Backtest Engine (MVP-3) tests.

Covers: market/limit execution, no look-ahead, commissions, slippage, position
accounting, FixedPercentageTP, deal/result statistics, reproducibility and
broker-agnosticism.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest import BacktestBroker, BacktestConfig, BacktestEngine
from app.domain.marketdata import Candle, Timeframe
from app.models.enums import OrderSide, OrderStatus
from app.strategies.config import (
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading.engine import TradingEngine
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"


def _candle(i: int, open_, high, low, close, volume=1000) -> Candle:
    return Candle(
        figi=FIGI,
        timeframe=Timeframe.MIN_5,
        timestamp=T0 + timedelta(minutes=i * 5),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
        is_complete=True,
    )


def _make_engine() -> BacktestEngine:
    broker = BacktestBroker()
    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    te = TradingEngine(broker, se, OrderManager(broker), PositionManager(), RiskManager())
    return BacktestEngine(te)


def _cfg(
    candles: list[Candle],
    *,
    direction: Direction = Direction.LONG,
    entry: EntryConfig | None = None,
    tp_percent: float = 10.0,
    initial_capital: str = "10000",
    quantity: str = "1",
    maker_fee: str = "0",
    taker_fee: str = "0",
    slippage: str = "0",
) -> BacktestConfig:
    strategy = StrategyConfig(
        direction=direction,
        entry=entry or EntryConfig(),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=tp_percent)),
    )
    return BacktestConfig(
        strategy=strategy,
        instrument_figi=FIGI,
        timeframe=Timeframe.MIN_5,
        candles=candles,
        initial_capital=Decimal(initial_capital),
        quantity=Decimal(quantity),
        maker_fee=Decimal(maker_fee),
        taker_fee=Decimal(taker_fee),
        slippage=Decimal(slippage),
        account_id="backtest",
    )


def _long_tp_candles() -> list[Candle]:
    # Unconditional entry fires at c0 close -> entry at c1 open (100.5).
    # TP target = 100.5 * 1.10 = 110.55; filled on c2 because c2.high >= 110.55.
    return [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100.5, 101, 100, 100.8),
        _candle(2, 100.8, 111, 100.5, 110.5),
    ]


def test_market_entry_fills_at_next_open() -> None:
    engine = _make_engine()
    result = engine.run(_cfg(_long_tp_candles(), tp_percent=10.0))
    assert len(result.deals) == 1
    deal = result.deals[0]
    # Signal at c0 close (100), entry filled at c1 open (100.5), not at close.
    assert deal.entry_price == Decimal("100.5")
    assert deal.entry_time == T0 + timedelta(minutes=5)
    assert deal.exit_price == Decimal("100.5") * Decimal("1.10")


def test_market_exit_fills_at_given_price() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI)
    broker.set_price(Decimal("100"))
    broker.execute_market(OrderSide.BUY, Decimal("2"), price=Decimal("100"), timestamp=T0)
    # Market exit fills at the next bar's open price.
    next_open = Decimal("105")
    order = broker.execute_market(
        OrderSide.SELL, Decimal("2"), price=next_open, timestamp=T0 + timedelta(minutes=5)
    )
    assert order.status == OrderStatus.FILLED
    assert order.price == next_open
    assert broker.is_open() is False
    # Realized gross = (exit - entry) * qty.
    assert broker.realized_gross_pnl() == (next_open - Decimal("100")) * Decimal("2")


def test_limit_order_execution() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI)
    order = broker.place_limit(OrderSide.BUY, Decimal("3"), Decimal("101"), timestamp=T0)
    assert order.status == OrderStatus.SUBMITTED
    # Bar with low <= 101 triggers the buy limit fill.
    fills = broker.on_bar(_candle(0, 100.5, 102, 100, 101))
    assert broker.is_open() is True
    assert broker.position_quantity() == Decimal("3")
    assert broker.average_price() == Decimal("101")
    assert broker.orders()[0].status == OrderStatus.FILLED
    assert len(fills) == 1
    # A bar that never reaches the limit does not fill.
    order2 = broker.place_limit(OrderSide.BUY, Decimal("1"), Decimal("99"), timestamp=T0)
    fills2 = broker.on_bar(_candle(1, 100.5, 103, 100.2, 102))
    assert fills2 == []
    assert order2.status == OrderStatus.SUBMITTED


def test_no_lookahead_bias() -> None:
    # Entry condition close > 100 only true at c1 close (105).
    from app.strategies.filters import (
        CandleSpec,
        ConstantValue,
        FilterCondition,
        FilterGroup,
        Operator,
    )

    cond = FilterCondition(
        arg1=CandleSpec(timeframe=Timeframe.MIN_5, series="close"),
        operator=Operator.GREATER_THAN,
        arg2=ConstantValue(value=100),
    )
    entry = EntryConfig(groups=[FilterGroup(conditions=[cond])])
    candles = [
        _candle(0, 100, 100.2, 99.8, 100),
        _candle(1, 100.1, 105, 100, 105),
        _candle(2, 105, 106, 104, 105.5),
        _candle(3, 106, 116, 105, 115),
    ]
    engine = _make_engine()
    result = engine.run(_cfg(candles, entry=entry, tp_percent=10.0))
    assert len(result.deals) == 1
    # Signal true at c1 close -> entry must be at c2 open, not c1 open.
    assert result.deals[0].entry_time == T0 + timedelta(minutes=10)
    assert result.deals[0].entry_price == Decimal("105")


def test_taker_commission_on_market() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI, taker_fee=Decimal("0.001"))
    broker.set_price(Decimal("100"))
    broker.execute_market(OrderSide.BUY, Decimal("5"), price=Decimal("100"), timestamp=T0)
    fee = Decimal("100") * Decimal("5") * Decimal("0.001")
    assert broker.deals()[0].commission == fee
    assert broker.fees_total() == fee
    assert broker.equity() == Decimal("10000") - fee


def test_maker_commission_on_limit() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI, maker_fee=Decimal("0.002"))
    broker.place_limit(OrderSide.BUY, Decimal("4"), Decimal("101"), timestamp=T0)
    broker.on_bar(_candle(0, 100.5, 102, 100, 101))
    fee = Decimal("101") * Decimal("4") * Decimal("0.002")
    assert broker.deals()[0].commission == fee


def test_slippage_on_market() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI, slippage=Decimal("0.01"))
    broker.set_price(Decimal("100"))
    # BUY fills higher by slippage; SELL fills lower.
    broker.execute_market(OrderSide.BUY, Decimal("1"), price=Decimal("100"), timestamp=T0)
    assert broker.deals()[0].price == Decimal("101")
    broker.execute_market(OrderSide.SELL, Decimal("1"), price=Decimal("100"), timestamp=T0)
    assert broker.deals()[1].price == Decimal("99")


def test_average_position_price() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI)
    broker.execute_market(OrderSide.BUY, Decimal("2"), price=Decimal("100"), timestamp=T0)
    broker.execute_market(OrderSide.BUY, Decimal("3"), price=Decimal("110"), timestamp=T0)
    assert broker.position_quantity() == Decimal("5")
    assert broker.average_price() == (
        (Decimal("2") * Decimal("100") + Decimal("3") * Decimal("110")) / Decimal("5")
    )


def test_realized_pnl() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI)
    broker.execute_market(OrderSide.BUY, Decimal("2"), price=Decimal("100"), timestamp=T0)
    broker.execute_market(OrderSide.SELL, Decimal("2"), price=Decimal("108"), timestamp=T0)
    assert broker.realized_gross_pnl() == Decimal("16")
    assert broker.is_open() is False


def test_unrealized_pnl() -> None:
    broker = BacktestBroker(initial_capital=Decimal("10000"), figi=FIGI)
    broker.execute_market(OrderSide.BUY, Decimal("3"), price=Decimal("50"), timestamp=T0)
    broker.set_price(Decimal("53"))
    assert broker.unrealized_pnl() == Decimal("9")


def test_fixed_percentage_tp_target() -> None:
    engine = _make_engine()
    result = engine.run(_cfg(_long_tp_candles(), tp_percent=10.0))
    deal = result.deals[0]
    assert deal.entry_price == Decimal("100.5")
    assert deal.exit_price == Decimal("110.55")  # 100.5 * 1.10


def test_full_sequence_entry_to_position_to_tp_to_deal() -> None:
    engine = _make_engine()
    result = engine.run(_cfg(_long_tp_candles()))
    assert result.num_trades == 1
    deal = result.deals[0]
    assert deal.gross_pnl == Decimal("10.05")
    assert deal.net_pnl == Decimal("10.05")
    assert deal.duration == timedelta(minutes=5)
    assert deal.executed_orders == 2
    assert result.executions is not None and len(result.executions) >= 2


def test_net_and_gross_differ_by_fees() -> None:
    engine = _make_engine()
    cfg = _cfg(_long_tp_candles(), taker_fee="0.001", maker_fee="0.002")
    result = engine.run(cfg)
    deal = result.deals[0]
    assert deal.net_pnl == deal.gross_pnl - deal.fees
    assert result.total_fees == deal.fees > 0
    assert result.net_pnl == result.gross_pnl - result.total_fees


def test_roi() -> None:
    engine = _make_engine()
    result = engine.run(_cfg(_long_tp_candles()))
    assert result.roi == result.net_pnl / Decimal("10000")
    assert result.final_capital == Decimal("10000") + result.net_pnl


def test_maximum_drawdown() -> None:
    # Unconditional LONG entry at c1 open; price falls after entry to produce a drawdown.
    candles = [
        _candle(0, 100, 101, 99, 100),
        _candle(1, 100, 101, 99, 100),
        _candle(2, 100, 101, 80, 85),
    ]
    engine = _make_engine()
    result = engine.run(_cfg(candles, tp_percent=100.0))
    # There is an open (unclosed) position at the end marked to market.
    assert result.max_drawdown > 0
    assert result.final_capital < Decimal("10000")


def test_reproducible_result() -> None:
    engine = _make_engine()
    cfg = _cfg(_long_tp_candles(), taker_fee="0.001")
    r1 = engine.run(cfg)
    r2 = engine.run(cfg)
    assert asdict(r1) == asdict(r2)


def test_strategy_and_backtest_are_broker_agnostic() -> None:
    import inspect

    import app.backtest
    import app.strategies

    def _sources(pkg):
        base = inspect.getsourcefile(pkg)
        import os

        folder = os.path.dirname(base)
        out = []
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    out.append(fh.read())
        return "\n".join(out)

    src = _sources(app.backtest) + _sources(app.strategies)
    assert "tinvest" not in src.lower()
    assert "TInvestAdapter" not in src
