"""SQLAlchemy persistence for Deal continuation state (MVP-6.12).

Implements the |DealStore| boundary on top of the existing PostgreSQL/ORM
infrastructure; this is the only place that touches SQLAlchemy for Deal state.
The trading domain (DealManager) depends only on the broker-neutral DealStore
protocol.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal import Deal as DealRow
from app.models.deal import DealLevel as DealLevelRow
from app.models.enums import OrderSide
from app.strategies.config import Direction
from app.trading.deal import (
    Deal,
    DealLevel,
    DealLevelStatus,
    DealStatus,
    utcnow,
)


def _to_domain_level(row: DealLevelRow) -> DealLevel:
    return DealLevel(
        index=row.level_index,
        side=OrderSide(row.side),
        price=Decimal(row.price) if row.price is not None else None,
        nominal=Decimal(row.nominal),
        quantity=Decimal(row.quantity),
        offset_percent=float(row.offset_percent),
        status=DealLevelStatus(row.status),
        is_market=row.is_market,
        filled_quantity=Decimal(row.filled_quantity),
        intent_id=row.intent_id,
        order_id=row.order_id,
        broker_order_id=row.broker_order_id,
    )


def _to_row_level(level: DealLevel, deal_id: int) -> DealLevelRow:
    return DealLevelRow(
        deal_id=deal_id,
        level_index=level.index,
        side=level.side.value,
        price=level.price,
        nominal=level.nominal,
        quantity=level.quantity,
        offset_percent=Decimal(str(level.offset_percent)),
        status=level.status.value,
        is_market=level.is_market,
        filled_quantity=level.filled_quantity,
        intent_id=level.intent_id,
        order_id=level.order_id,
        broker_order_id=level.broker_order_id,
    )


def _to_domain(row: DealRow, levels: list[DealLevelRow]) -> Deal:
    return Deal(
        id=row.id,
        bot_id=row.bot_id,
        instrument_figi=row.instrument_figi,
        direction=Direction(row.direction),
        status=DealStatus(row.status),
        deposit=Decimal(row.deposit) if row.deposit is not None else None,
        base_nominal=Decimal(row.base_nominal),
        reference_price=Decimal(row.reference_price),
        lot_size=row.lot_size,
        tick_size=Decimal(row.tick_size) if row.tick_size is not None else None,
        tp_percent=float(row.tp_percent),
        active_limit=row.active_limit,
        account_id=row.account_id,
        average_price=Decimal(row.average_price),
        tp_rev=row.tp_rev,
        tp_price=Decimal(row.tp_price) if row.tp_price is not None else None,
        tp_quantity=Decimal(row.tp_quantity) if row.tp_quantity is not None else None,
        tp_intent_id=row.tp_intent_id,
        tp_order_id=row.tp_order_id,
        tp_broker_order_id=row.tp_broker_order_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
        levels=[_to_domain_level(lvl) for lvl in levels],
    )


class SqlAlchemyDealStore:
    """Persists Deal state in PostgreSQL/SQLite via the ORM (flush semantics)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, deal: Deal) -> Deal:
        if deal.id is None:
            row = DealRow(
                bot_id=deal.bot_id,
                instrument_figi=deal.instrument_figi,
                direction=deal.direction.value,
                status=deal.status.value,
                deposit=deal.deposit,
                base_nominal=deal.base_nominal,
                reference_price=deal.reference_price,
                lot_size=deal.lot_size,
                tick_size=deal.tick_size,
                tp_percent=Decimal(str(deal.tp_percent)),
                active_limit=deal.active_limit,
                account_id=deal.account_id,
                average_price=deal.average_price,
                tp_rev=deal.tp_rev,
                tp_price=deal.tp_price,
                tp_quantity=deal.tp_quantity,
                tp_intent_id=deal.tp_intent_id,
                tp_order_id=deal.tp_order_id,
                tp_broker_order_id=deal.tp_broker_order_id,
                created_at=deal.created_at,
                updated_at=utcnow(),
                closed_at=deal.closed_at,
            )
            self._session.add(row)
            await self._session.flush()
            deal.id = row.id
        else:
            row = await self._session.get(DealRow, deal.id)
            if row is None:
                raise KeyError(f"deal {deal.id} not found")
            row.bot_id = deal.bot_id
            row.instrument_figi = deal.instrument_figi
            row.direction = deal.direction.value
            row.status = deal.status.value
            row.deposit = deal.deposit
            row.base_nominal = deal.base_nominal
            row.reference_price = deal.reference_price
            row.lot_size = deal.lot_size
            row.tick_size = deal.tick_size
            row.tp_percent = Decimal(str(deal.tp_percent))
            row.active_limit = deal.active_limit
            row.account_id = deal.account_id
            row.average_price = deal.average_price
            row.tp_rev = deal.tp_rev
            row.tp_price = deal.tp_price
            row.tp_quantity = deal.tp_quantity
            row.tp_intent_id = deal.tp_intent_id
            row.tp_order_id = deal.tp_order_id
            row.tp_broker_order_id = deal.tp_broker_order_id
            row.updated_at = utcnow()
            row.closed_at = deal.closed_at
            await self._session.execute(
                delete(DealLevelRow).where(DealLevelRow.deal_id == deal.id)
            )
        for level in deal.levels:
            self._session.add(_to_row_level(level, deal.id))
        await self._session.flush()
        return deal

    async def get(self, deal_id: int) -> Deal | None:
        row = await self._session.get(DealRow, deal_id)
        if row is None:
            return None
        levels = (
            (
                await self._session.execute(
                    select(DealLevelRow)
                    .where(DealLevelRow.deal_id == deal_id)
                    .order_by(DealLevelRow.level_index)
                )
            )
            .scalars()
            .all()
        )
        return _to_domain(row, list(levels))

    async def list_unclosed(self) -> list[Deal]:
        rows = (
            (await self._session.execute(select(DealRow).where(DealRow.status != "CLOSED")))
            .scalars()
            .all()
        )
        deals = []
        for row in rows:
            levels = (
                (
                    await self._session.execute(
                        select(DealLevelRow)
                        .where(DealLevelRow.deal_id == row.id)
                        .order_by(DealLevelRow.level_index)
                    )
                )
                .scalars()
                .all()
            )
            deals.append(_to_domain(row, list(levels)))
        return deals
