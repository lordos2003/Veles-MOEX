"""T-Invest streaming execution events (MVP-6.2).

The T-Invest Open API exposes two server-side streams used for live execution:

- OrderStateStream  -> order-state changes (plus a list of trades on each state).
- TradesStream      -> individual executions.

This module turns their messages into broker-neutral events
(``OrderUpdate``, ``TradeFill``, ``PositionUpdate``) and delivers them to a
broker-neutral handler (the OrderManager). It never leaks T-Invest message
types above this layer.

The transport (how bytes/JSON frames are read) is abstracted behind
|TInvestStreamTransport| so that the manager can be driven deterministically in
tests and a real WebSocket/gRPC transport can be plugged in later. Recovery
after a reconnect is performed through the unary `BrokerAdapter` methods.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Protocol

from app.brokers.tinvest import _quotation_to_decimal, _timestamp_to_datetime
from app.models.enums import OrderStatus
from app.trading.domain import OrderState, OrderUpdate, PositionUpdate, TradeFill

logger = logging.getLogger(__name__)

# T-Invest execution_report_status -> internal OrderState.
_STREAM_STATUS_TO_STATE = {
    "EXECUTION_REPORT_STATUS_NEW": OrderState.SUBMITTED,
    "EXECUTION_REPORT_STATUS_PARTIALLYFILL": OrderState.PARTIALLY_FILLED,
    "EXECUTION_REPORT_STATUS_FILL": OrderState.FILLED,
    "EXECUTION_REPORT_STATUS_REJECTED": OrderState.REJECTED,
    "EXECUTION_REPORT_STATUS_CANCELLED": OrderState.CANCELLED,
}

# Broker-neutral OrderStatus -> internal OrderState (used for unary recovery).
_ORDER_STATUS_TO_STATE = {
    OrderStatus.NEW: OrderState.SUBMITTED,
    OrderStatus.SUBMITTED: OrderState.SUBMITTED,
    OrderStatus.PARTIALLY_FILLED: OrderState.PARTIALLY_FILLED,
    OrderStatus.FILLED: OrderState.FILLED,
    OrderStatus.CANCELLED: OrderState.CANCELLED,
    OrderStatus.REJECTED: OrderState.REJECTED,
    OrderStatus.EXPIRED: OrderState.CANCELLED,
    OrderStatus.ERROR: OrderState.FAILED,
    OrderStatus.UNKNOWN: OrderState.UNKNOWN,
}


class StreamHandler(Protocol):
    """Broker-neutral receiver of execution events (implemented by OrderManager)."""

    def on_order_update(self, update: OrderUpdate) -> None: ...

    def on_trade_fill(self, trade: TradeFill) -> None: ...

    def on_position_update(self, update: PositionUpdate) -> None: ...


class TInvestStreamTransport(ABC):
    """Transport seam: connects, (re)subscribes and yields parsed messages.

    Messages are returned as plain ``dict`` with the documented T-Invest JSON
    structure (``order_state`` / ``order_trades`` / ``position`` / ``ping`` /
    ``subscription``). A production transport maps the wire/payload format into
    these dictionaries; tests inject a scripted transport.
    """

    @abstractmethod
    async def connect(self, accounts: list[str]) -> None:
        """Open the connection and subscribe to the given accounts."""

    @abstractmethod
    def messages(self) -> AsyncIterator[dict]:
        """Yield parsed stream messages until the connection ends."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""


class TInvestStreamManager:
    """Orchestrates order/trade/position streaming, reconnect and recovery.

    Responsibilities: subscribe, dispatch broker-neutral events, keep-alive
    (pass-through of ping), exponential-backoff reconnect, and unary recovery
    after every reconnect.
    """

    def __init__(
        self,
        adapter: object,
        transport: TInvestStreamTransport,
        handler: StreamHandler,
        account_id: str,
        *,
        backoff: tuple[float, ...] = (1.0, 10.0, 60.0),
        max_backoff: float = 60.0,
    ) -> None:
        self._adapter = adapter
        self._transport = transport
        self._handler = handler
        self._account_id = account_id
        self._backoff = backoff
        self._max_backoff = max_backoff
        self._stopped = False

    def stop(self) -> None:
        """Request the run loop to stop and the session to be closed."""
        self._stopped = True

    async def run(self) -> None:
        """Process events until :meth:`stop` is called."""
        self._stopped = False
        attempt = 0
        while not self._stopped:
            try:
                await self._run_session()
                attempt = 0
            except asyncio.CancelledError:
                await self._safe_close()
                raise
            except Exception as exc:  # noqa: BLE001 - stream lifecycle must never crash the bot
                logger.warning("stream session failed: %s", exc)
            finally:
                await self._safe_close()
            if self._stopped:
                break
            if not self._backoff:
                delay = self._max_backoff
            else:
                index = attempt if attempt < len(self._backoff) else len(self._backoff) - 1
                delay = min(self._backoff[index], self._max_backoff)
            logger.debug("reconnecting stream in %.0fs", delay)
            await asyncio.sleep(delay)
            attempt += 1

    async def _run_session(self) -> None:
        await self._transport.connect([self._account_id])
        logger.debug("stream connected for account %s", self._account_id)
        await self._recover()
        async for message in self._transport.messages():
            await self._dispatch(message)

    async def _dispatch(self, message: dict) -> None:
        if not message:
            return
        if "order_state" in message:
            for event in _decode_order_state(message["order_state"]):
                await self._deliver(event)
        elif "order_trades" in message:
            for event in _decode_trades(message["order_trades"]):
                await self._deliver(event)
        elif "position" in message:
            event = _decode_position(message["position"])
            if event is not None:
                await self._deliver(event)

    async def _deliver(self, event: object) -> None:
        if isinstance(event, OrderUpdate):
            self._handler.on_order_update(event)
        elif isinstance(event, TradeFill):
            self._handler.on_trade_fill(event)
        elif isinstance(event, PositionUpdate):
            self._handler.on_position_update(event)

    async def _recover(self) -> None:
        """Reconcile order/position state via unary API after a (re)connect."""
        try:
            for broker_order in await self._adapter.get_orders(self._account_id):
                update = OrderUpdate(
                    broker_order_id=broker_order.order_id,
                    status=_order_status_to_state(broker_order.status),
                    reject_info=broker_order.reject_info,
                    timestamp=broker_order.updated_at,
                )
                self._handler.on_order_update(update)
        except Exception as exc:  # noqa: BLE001 - recovery must not crash the stream loop
            logger.warning("order recovery failed: %s", exc)
        try:
            for position in await self._adapter.get_open_positions(self._account_id):
                update = PositionUpdate(
                    instrument_figi=position.instrument_figi,
                    quantity=position.quantity,
                    average_price=position.average_price,
                    current_price=position.current_price,
                    unrealized_pnl=position.unrealized_pnl,
                    timestamp=position.timestamp,
                )
                self._handler.on_position_update(update)
        except Exception as exc:  # noqa: BLE001 - recovery must not crash the stream loop
            logger.warning("position recovery failed: %s", exc)

    async def _safe_close(self) -> None:
        try:
            await self._transport.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("stream close failed: %s", exc)


def _stream_status_to_state(value: str | None) -> OrderState:
    return _STREAM_STATUS_TO_STATE.get(value or "", OrderState.UNKNOWN)


def _order_status_to_state(status: OrderStatus) -> OrderState:
    return _ORDER_STATUS_TO_STATE.get(status, OrderState.UNKNOWN)


def _decode_order_state(order_state: dict) -> list[OrderUpdate | TradeFill]:
    """Decode an OrderStateStream ``order_state`` message into broker-neutral events."""
    events: list[OrderUpdate | TradeFill] = []
    order_id = order_state.get("order_id", "")
    idempotency_key = _uuid_or_none(order_state.get("order_request_id"))
    status = _stream_status_to_state(order_state.get("execution_report_status"))
    events.append(
        OrderUpdate(
            broker_order_id=order_id,
            status=status,
            idempotency_key=idempotency_key,
            reject_info=order_state.get("status_info", {}).get("message"),
            timestamp=_timestamp_to_datetime(order_state.get("completion_time"))
            or _timestamp_to_datetime(order_state.get("created_at")),
        )
    )
    for trade in order_state.get("trades") or []:
        events.append(_trade_to_fill(trade, order_id, idempotency_key))
    return events


def _decode_trades(order_trades: dict) -> list[TradeFill]:
    """Decode a TradesStream ``order_trades`` message into individual fills."""
    order_id = order_trades.get("order_id", "")
    return [
        _trade_to_fill(trade, order_id, None)
        for trade in order_trades.get("trades") or []
    ]


def _trade_to_fill(trade: dict, broker_order_id: str, idempotency_key: str | None) -> TradeFill:
    return TradeFill(
        execution_id=trade.get("trade_id", ""),
        broker_order_id=broker_order_id,
        idempotency_key=idempotency_key,
        quantity=Decimal(str(trade.get("quantity") or 0)),
        price=_quotation_to_decimal(trade.get("price")) or Decimal("0"),
        timestamp=_timestamp_to_datetime(trade.get("date_time")),
    )


def _decode_position(position: dict) -> PositionUpdate | None:
    """Decode a PositionsStream ``position`` message into a PositionUpdate.

    The broker stream carries a quantity/balance but not a weighted average
    price; the average is preserved by the PositionManager when absent.
    """
    securities = position.get("securities") or []
    if not securities:
        return None
    # MVP-6.2 scope is shares/ETF; take the first security present.
    security = securities[0]
    return PositionUpdate(
        instrument_figi=security.get("figi", ""),
        quantity=Decimal(str(security.get("balance") or 0)),
        timestamp=_timestamp_to_datetime(position.get("date")),
    )


def _uuid_or_none(value: str | None) -> str | None:
    if value:
        try:
            import uuid

            return str(uuid.UUID(value))
        except ValueError:
            return value
    return None
