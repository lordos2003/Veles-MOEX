"""Backtest API (MVP-7.0 R7/R8).

``POST /api/backtests`` runs a synchronous backtest over broker candles for a
strategy (immutable version or inline config) and an instrument. Fees, slippage
and the deal deposit are required explicitly; no financial default is invented.
The result is returned in the response and is NOT persisted in MVP-7.0.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_instrument_service,
    get_market_data_service,
    get_session,
    get_settings_dep,
    get_strategy_service,
)
from app.backtest import BacktestBroker, BacktestConfig, BacktestEngine
from app.backtest.models import BacktestDeal, BacktestResult
from app.backtest.schemas import (
    BacktestDealResponse,
    BacktestExecutionResponse,
    BacktestOrderResponse,
    BacktestRequest,
    BacktestResponse,
)
from app.brokers.base import BrokerDeal, BrokerOrder
from app.brokers.tinvest_errors import InstrumentNotFoundError, InvalidRequestError
from app.core.config import Settings
from app.domain.marketdata import Timeframe
from app.services.instruments import InstrumentService
from app.services.market_data import MarketDataService, timeframe_seconds
from app.strategies.config import StrategyConfig
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.strategies.service import StrategyService
from app.trading.engine import TradingEngine
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager
from app.trading.sizing import SizingError

router = APIRouter(prefix="/backtests", tags=["backtest"])


def _validation_message(exc: ValidationError) -> str:
    """First user-facing validation error (MVP-7.2 I4/I5).

    pydantic prefixes model-validator messages with "Value error, "; API
    consumers get the clean Russian message (e.g. "Индикатор RSI: укажите
    параметр «период».").
    """
    msg = exc.errors()[0]["msg"]
    return msg.removeprefix("Value error, ")


def _estimate_candle_count(timeframe: Timeframe, start: datetime, end: datetime) -> int | None:
    """Calendar estimate of the candle count, or ``None`` for mixed tz periods.

    A pure calendar bound (span / duration) is an over-estimate: trading
    sessions are shorter than calendar time. It exists only to reject clearly
    oversized ranges before any broker request (B2); the authoritative check
    stays the actual fetched count.
    """
    if (start.tzinfo is None) != (end.tzinfo is None):
        return None
    span_seconds = (end - start).total_seconds()
    return max(1, int(span_seconds // timeframe_seconds(timeframe)) + 1)


def _make_backtest_engine() -> BacktestEngine:
    """Build a BacktestEngine on a placeholder broker (same wiring as tests).

    ``BacktestEngine.run`` drives execution through its own |BacktestBroker|;
    the outer TradingEngine broker is only a construction requirement.
    """
    placeholder = BacktestBroker()
    strategy = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    trading = TradingEngine(
        placeholder, strategy, OrderManager(placeholder), PositionManager(), RiskManager()
    )
    return BacktestEngine(trading)


def _deal_response(deal: BacktestDeal) -> BacktestDealResponse:
    return BacktestDealResponse(
        deal_id=deal.deal_id,
        direction=deal.direction,
        entry_time=deal.entry_time,
        exit_time=deal.exit_time,
        entry_price=deal.entry_price,
        exit_price=deal.exit_price,
        quantity=deal.quantity,
        gross_pnl=deal.gross_pnl,
        fees=deal.fees,
        net_pnl=deal.net_pnl,
        duration_seconds=deal.duration.total_seconds(),
        executed_orders=deal.executed_orders,
        reason=deal.reason,
    )


def _execution_response(fill: BrokerDeal) -> BacktestExecutionResponse:
    return BacktestExecutionResponse(
        deal_id=fill.deal_id,
        instrument_figi=fill.instrument_figi,
        side=fill.side,
        quantity=fill.quantity,
        price=fill.price,
        account_id=fill.account_id,
        order_id=fill.order_id,
        commission=fill.commission,
        currency=fill.currency,
        happened_at=fill.happened_at,
    )


def _order_response(order: BrokerOrder) -> BacktestOrderResponse:
    return BacktestOrderResponse(
        order_id=order.order_id,
        status=order.status,
        account_id=order.account_id,
        instrument_figi=order.instrument_figi,
        type=order.type,
        side=order.side,
        requested_quantity=order.requested_quantity,
        executed_quantity=order.executed_quantity,
        price=order.price,
        executed_average_price=order.executed_average_price,
        currency=order.currency,
        created_at=order.created_at,
        updated_at=order.updated_at,
        reject_info=order.reject_info,
    )


def _result_response(result: BacktestResult) -> BacktestResponse:
    return BacktestResponse(
        initial_capital=result.initial_capital,
        final_capital=result.final_capital,
        gross_pnl=result.gross_pnl,
        net_pnl=result.net_pnl,
        roi=result.roi,
        total_fees=result.total_fees,
        num_trades=result.num_trades,
        winning_trades=result.winning_trades,
        losing_trades=result.losing_trades,
        win_rate=result.win_rate,
        average_trade=result.average_trade,
        average_duration=result.average_duration,
        max_drawdown=result.max_drawdown,
        deals=[_deal_response(deal) for deal in result.deals],
        orders=[_order_response(order) for order in result.orders],
        executions=[_execution_response(fill) for fill in result.executions],
    )


@router.post("", response_model=BacktestResponse)
async def run_backtest(
    payload: BacktestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    strategy_service: Annotated[StrategyService, Depends(get_strategy_service)],
    instrument_service: Annotated[InstrumentService, Depends(get_instrument_service)],
    market_data: Annotated[MarketDataService, Depends(get_market_data_service)],
) -> BacktestResponse:
    """Run a synchronous backtest; the result is not persisted."""
    # Resolve the strategy configuration (immutable version or inline).
    if payload.config is not None:
        strategy_config = payload.config
        strategy_version_id = None
    else:
        version = await strategy_service.get_version(payload.strategy_version_id)
        if version is None:
            raise HTTPException(
                status_code=404, detail=f"strategy version {payload.strategy_version_id} not found"
            )
        try:
            strategy_config = StrategyConfig.model_validate(version.config)
        except ValidationError as exc:
            # MVP-7.2 I5: an old version saved before indicator params became
            # required is a 422 with the first user-facing error, not a 500.
            raise HTTPException(
                status_code=422, detail=_validation_message(exc)
            ) from exc
        strategy_version_id = version.id

    # B3: the run must reproduce the strategy's own timeframe; a mismatch would
    # silently evaluate its indicators on another interval than in live trading.
    if strategy_config.timeframe is not None and strategy_config.timeframe != payload.timeframe:
        raise HTTPException(
            status_code=422,
            detail=(
                f"strategy timeframe {strategy_config.timeframe} does not match the "
                f"request timeframe {payload.timeframe}"
            ),
        )

    # Resolve the instrument; the deposit path (R8) requires lot and tick sizes
    # and a currency (no defaults, like live).
    instrument = await instrument_service.get_by_id(payload.instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"instrument {payload.instrument_id} not found")
    if instrument.lot_size is None or instrument.lot_size <= 0:
        raise HTTPException(
            status_code=422,
            detail=(
                f"instrument {payload.instrument_id} ({instrument.figi}) has no lot_size; "
                "the deposit path cannot size orders (no default lot)"
            ),
        )
    if instrument.tick_size is None or instrument.tick_size <= 0:
        raise HTTPException(
            status_code=422,
            detail=(
                f"instrument {payload.instrument_id} ({instrument.figi}) has no tick_size; "
                "the backtest is blocked (no default tick)"
            ),
        )

    # Candles: existing broker path, chunked by the MarketDataService.
    # B2: reject a clearly oversized range BEFORE any broker request; the
    # fetched-count check below stays as the authoritative guard.
    estimate = _estimate_candle_count(payload.timeframe, payload.from_, payload.to)
    if estimate is not None and estimate > settings.backtest_max_candles:
        raise HTTPException(
            status_code=422,
            detail=(
                f"period from {payload.from_} to {payload.to} estimates {estimate} "
                f"{payload.timeframe} candles, exceeding backtest_max_candles "
                f"({settings.backtest_max_candles})"
            ),
        )
    try:
        candles = await market_data.get_candles(
            instrument.figi, payload.timeframe, payload.from_, payload.to
        )
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(candles) > settings.backtest_max_candles:
        raise HTTPException(
            status_code=422,
            detail=(
                f"requested {len(candles)} candles exceeds backtest_max_candles "
                f"({settings.backtest_max_candles})"
            ),
        )

    backtest_config = BacktestConfig(
        strategy=strategy_config,
        instrument_figi=instrument.figi,
        timeframe=payload.timeframe,
        candles=candles,
        strategy_version_id=strategy_version_id,
        deposit=payload.deposit,
        lot_size=instrument.lot_size,
        currency=instrument.currency,
        maker_fee=payload.maker_fee,
        taker_fee=payload.taker_fee,
        slippage=payload.slippage,
        # B1: the run's capital is the deal deposit — no invented 10 000. The
        # reply's initial_capital / final_capital / roi are derived from it.
        initial_capital=payload.deposit,
        account_id="backtest",
    )
    try:
        result = _make_backtest_engine().run(backtest_config)
    except SizingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _result_response(result)
