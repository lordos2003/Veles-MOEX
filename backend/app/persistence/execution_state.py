"""SQLAlchemy persistence for the live execution domain (MVP-6.3).

Implements the |LiveStateStore| boundary on top of the existing
PostgreSQL/ORM infrastructure. This module is the only place that touches
SQLAlchemy for live execution state; the trading domain (OrderManager /
PositionManager) depends only on the broker-neutral snapshot/store Protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderSide, OrderType
from app.models.live_execution import LiveFill, LiveIntent, LiveOrder, LivePosition
from app.trading.domain import ExecutionIntent, Fill, InternalOrder, OrderState
from app.trading.position_manager import Position
from app.trading.state import LiveStateSnapshot


def _to_domain_intent(row: LiveIntent) -> ExecutionIntent:
    return ExecutionIntent(
        intent_id=row.intent_id,
        trade_id=row.trade_id,
        instrument_figi=row.instrument_figi,
        side=OrderSide(row.side),
        order_type=OrderType(row.order_type),
        quantity=Decimal(row.quantity),
        limit_price=Decimal(row.limit_price) if row.limit_price is not None else None,
        reason=row.reason,
        account_id=row.account_id,
        created_at=row.created_at,
        idempotency_key=row.idempotency_key,
    )


def _to_row_intent(intent: ExecutionIntent) -> LiveIntent:
    return LiveIntent(
        intent_id=intent.intent_id,
        trade_id=intent.trade_id,
        instrument_figi=intent.instrument_figi,
        side=intent.side.value,
        order_type=intent.order_type.value,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        reason=intent.reason,
        account_id=intent.account_id,
        idempotency_key=intent.idempotency_key,
        created_at=intent.created_at,
    )


def _to_domain_order(row: LiveOrder) -> InternalOrder:
    return InternalOrder(
        order_id=row.order_id,
        intent_id=row.intent_id,
        instrument_figi=row.instrument_figi,
        side=OrderSide(row.side),
        order_type=OrderType(row.order_type),
        requested_quantity=Decimal(row.requested_quantity),
        limit_price=Decimal(row.limit_price) if row.limit_price is not None else None,
        idempotency_key=row.idempotency_key,
        account_id=row.account_id,
        broker_order_id=row.broker_order_id,
        filled_quantity=Decimal(row.filled_quantity),
        average_fill_price=Decimal(row.average_fill_price),
        status=OrderState(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        reject_info=row.reject_info,
    )


def _to_row_order(order: InternalOrder) -> LiveOrder:
    return LiveOrder(
        order_id=order.order_id,
        intent_id=order.intent_id,
        instrument_figi=order.instrument_figi,
        side=order.side.value,
        order_type=order.order_type.value,
        requested_quantity=order.requested_quantity,
        limit_price=order.limit_price,
        idempotency_key=order.idempotency_key,
        account_id=order.account_id,
        broker_order_id=order.broker_order_id,
        filled_quantity=order.filled_quantity,
        average_fill_price=order.average_fill_price,
        status=order.status.value,
        reject_info=order.reject_info,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _to_domain_fill(row: LiveFill) -> Fill:
    return Fill(
        fill_id=row.fill_id,
        internal_order_id=row.internal_order_id,
        quantity=Decimal(row.quantity),
        price=Decimal(row.price),
        fee=Decimal(row.fee),
        broker_execution_id=row.broker_execution_id,
        timestamp=row.timestamp,
    )


def _to_row_fill(fill: Fill) -> LiveFill:
    return LiveFill(
        fill_id=fill.fill_id,
        internal_order_id=fill.internal_order_id,
        quantity=fill.quantity,
        price=fill.price,
        fee=fill.fee,
        broker_execution_id=fill.broker_execution_id,
        timestamp=fill.timestamp,
    )


def _to_domain_position(row: LivePosition) -> Position:
    return Position(
        instrument_figi=row.instrument_figi,
        quantity=Decimal(row.quantity),
        average_price=Decimal(row.average_price),
        realized_pnl=Decimal(row.realized_pnl),
        fees=Decimal(row.fees),
        current_price=Decimal(row.current_price) if row.current_price is not None else None,
        unrealized_pnl=Decimal(row.unrealized_pnl),
        updated_at=row.updated_at,
    )


def _to_row_position(pos: Position) -> LivePosition:
    return LivePosition(
        instrument_figi=pos.instrument_figi,
        quantity=pos.quantity,
        average_price=pos.average_price,
        realized_pnl=pos.realized_pnl,
        fees=pos.fees,
        current_price=pos.current_price,
        unrealized_pnl=pos.unrealized_pnl,
        updated_at=pos.updated_at or datetime.now(UTC),
    )


async def _upsert(session: AsyncSession, model, row) -> None:
    """Insert or update a single ORM row by primary key."""
    pk_name = model.__table__.primary_key.columns[0].name
    existing = await session.get(model, getattr(row, pk_name))
    if existing is None:
        session.add(row)
    else:
        for column in row.__table__.columns:
            setattr(existing, column.name, getattr(row, column.name))


class SqlAlchemyLiveStateStore:
    """Persists the live execution snapshot in PostgreSQL/SQLite via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_snapshot(self, snapshot: LiveStateSnapshot) -> None:
        for intent in snapshot.intents:
            await _upsert(self._session, LiveIntent, _to_row_intent(intent))
        for order in snapshot.orders:
            await _upsert(self._session, LiveOrder, _to_row_order(order))
        for fill in snapshot.fills:
            await _upsert(self._session, LiveFill, _to_row_fill(fill))
        for position in snapshot.positions:
            await _upsert(self._session, LivePosition, _to_row_position(position))
        await self._session.flush()

    async def load_snapshot(self) -> LiveStateSnapshot:
        intents = (await self._session.execute(select(LiveIntent))).scalars().all()
        orders = (await self._session.execute(select(LiveOrder))).scalars().all()
        fills = (await self._session.execute(select(LiveFill))).scalars().all()
        positions = (await self._session.execute(select(LivePosition))).scalars().all()
        return LiveStateSnapshot(
            intents=[_to_domain_intent(row) for row in intents],
            orders=[_to_domain_order(row) for row in orders],
            fills=[_to_domain_fill(row) for row in fills],
            positions=[_to_domain_position(row) for row in positions],
        )
