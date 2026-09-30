"""MVP-6.12 Deal Manager (broker-neutral deal lifecycle).

Owns the live Deal lifecycle (D2/D3/D4/D5): a Deal is one position cycle from
the FLAT entry to the closing take-profit fill. The manager is broker-neutral —
it submits intents through the |OrderManager| / |RiskManager| and follows fills
through the OrderManager's synchronous fill listener into an async pump. At most
one Deal per bot is active; fills are correlated by ``bot_id`` and by the
deterministic ``deal-{id}-...`` intent ids. The take-profit is Deal-owned and is
re-armed from the |PositionManager| facts on every grid fill (D4).

No Veles semantics are invented here: the DCA-grid math (DCAGridEngine) and the
fixed-percentage TP math are reused unchanged; the MOEX lot/tick rounding is the
same C3/D3 contract as the rest of the live path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

from app.models.enums import OrderSide, OrderType
from app.strategies.config import Direction, StrategyConfig
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.dca_grid import LevelStatus as GridLevelStatus
from app.trading.deal import (
    Deal,
    DealBlocked,
    DealError,
    DealLevel,
    DealLevelStatus,
    DealOrderRejected,
    DealPositionContradiction,
    DealReconciliationRequired,
    DealStatus,
    DealStore,
    DealTickSizeInvalid,
    align_grid_price,
    align_tp_price,
    deal_grid_intent_id,
    deal_tp_intent_id,
    utcnow,
)
from app.trading.domain import (
    TERMINAL_STATES,
    ExecutionIntent,
    Fill,
    InternalOrder,
    OrderState,
)
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager, RiskRejected
from app.trading.sizing import LotSizeUnavailable, SizingBelowLot


def _round_down_lots(quantity: Decimal, lot_size: int | None) -> Decimal:
    """C3: round a quantity down to a whole number of lots (no default lot)."""
    if lot_size is None or lot_size <= 0:
        raise LotSizeUnavailable(
            f"a positive lot size is required for C3 rounding, got {lot_size!r}"
        )
    lot = Decimal(int(lot_size))
    return (quantity // lot) * lot


def _execute_side(direction: Direction) -> OrderSide:
    return OrderSide.SELL if direction == Direction.LONG else OrderSide.BUY


def _sign_matches(quantity: Decimal, direction: Direction) -> bool:
    if direction == Direction.LONG:
        return quantity > 0
    return quantity < 0


class DealManager:
    """Owns the live Deal lifecycle over a broker-neutral OrderManager."""

    def __init__(
        self,
        store: DealStore,
        order_manager: OrderManager,
        risk_manager: RiskManager,
        *,
        # B2: broker-neutral callback that surfaces a deal failure to the bot
        # lifecycle (production wires bot ERROR + persistence; tests capture).
        on_bot_error: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._om = order_manager
        self._rm = risk_manager
        self._pm: PositionManager = order_manager.positions()
        self._deals: dict[int, Deal] = {}
        self._blocked: set[int] = set()
        self._pending: list[tuple[InternalOrder, Fill]] = []
        self._last_error: DealError | None = None
        self._errors: dict[int, str] = {}
        self._on_bot_error = on_bot_error
        # Fills arrive on the synchronous stream path; the async reactions are
        # drained by pump() (production wires pump to the stream's per-batch hook).
        order_manager.fill_listener = self._on_order_fill

    # --- state ---------------------------------------------------------------------

    @property
    def blocked_bots(self) -> set[int]:
        """Bots whose new deal submissions are blocked (ERROR / unreconciled)."""
        return set(self._blocked)

    @property
    def last_error(self) -> DealError | None:
        return self._last_error

    def last_error_for(self, bot_id: int) -> str | None:
        """B2: the last deal-failure reason for one bot (observable via the API)."""
        return self._errors.get(bot_id)

    def active_deal(self, bot_id: int) -> Deal | None:
        return self._deals.get(bot_id)

    # --- failure surfacing (B2) -------------------------------------------------

    async def _fail_deal(
        self, bot_id: int | None, deal: Deal | None, exc: Exception
    ) -> None:
        """Mark a Deal ERROR, block new submissions and surface the failure.

        B2: the bot lifecycle is notified through the broker-neutral
        ``on_bot_error`` callback; the reason is kept observable via
        :meth:`last_error_for`. Every failure path (``pump()``, ``open_deal()``,
        recovery) funnels through here so no deal error is ever silent.
        """
        error = exc if isinstance(exc, DealError) else DealReconciliationRequired(str(exc))
        self._last_error = error
        if deal is not None and deal.status is not DealStatus.CLOSED:
            deal.status = DealStatus.ERROR
            deal.updated_at = utcnow()
            try:
                await self._store.save(deal)
            except Exception:  # noqa: BLE001 - the in-memory ERROR block is already set
                # B1: even a failing store must not let the failure escape the
                # per-event boundary; the in-memory block + reason stay intact.
                pass
        if bot_id is None:
            return
        self._blocked.add(bot_id)
        self._errors[bot_id] = str(error)
        await self._notify_bot_error(bot_id, str(error))

    async def _notify_bot_error(self, bot_id: int | None, reason: str) -> None:
        """Best-effort notification of the bot lifecycle (B2).

        The Deal layer already guarantees the safety invariant (Deal ERROR,
        block); the lifecycle notification is a secondary surfacing path and a
        callback failure must not lose the primary block or the reason.
        """
        if self._on_bot_error is None or bot_id is None:
            return
        try:
            await self._on_bot_error(bot_id, reason)
        except Exception:  # noqa: BLE001 - surfacing must not break the deal block
            pass

    async def assert_deal_for_open_position(self, bot_id: int, figi: str) -> None:
        """B2/D5: an OPEN position must be owned by a non-CLOSED Deal.

        The live cycle refuses to continue over an OPEN position without a
        Deal (e.g. after a restart or a failure that lost the owner): the bot
        goes to ERROR with an explicit reason — the D5 contradiction is never
        silently ignored.
        """
        if bot_id in self._deals:
            return
        reason = (
            f"bot {bot_id}: position {figi} is OPEN but no owning non-CLOSED "
            "Deal exists; live cycle stopped for reconciliation (D5/B2)"
        )
        await self._notify_bot_error(bot_id, reason)
        raise DealPositionContradiction(reason)

    # --- entry (D2) -----------------------------------------------------------------

    async def open_deal(
        self,
        *,
        bot_id: int,
        instrument_figi: str,
        direction: Direction,
        config: StrategyConfig,
        reference_price: Decimal,
        deposit: Decimal | None,
        base_nominal: Decimal,
        account_id: str | None,
        lot_size: int | None,
        tick_size: Decimal | None,
    ) -> Deal:
        """Open a Deal: build the whole grid, persist it, then submit orders.

        D1 already rejected unsupported configurations at START; here the
        supported math is reused unchanged (DCAGridEngine on the snapshot price).
        C3 rounds **every** level down to whole lots (any 0-lot level blocks the
        whole entry), D3 aligns every limit price to the tick (missing tick
        blocks the whole entry), and the Deal is persisted **before** the first
        order is placed.
        """
        if bot_id in self._blocked:
            raise DealBlocked(
                f"bot {bot_id} has a deal needing reconciliation; new deal "
                "submissions are blocked (MVP-6.12 D4/D5)"
            )
        if bot_id in self._deals:
            raise DealBlocked(
                f"bot {bot_id} already has an open deal; no second deal is opened"
            )
        deal: Deal | None = None
        try:
            grid = DCAGridEngine().build(
                config.dca_grid, reference_price, direction, base_nominal=base_nominal
            )
            limit_levels = [lvl for lvl in grid.levels if not lvl.is_market]
            if limit_levels and (tick_size is None or tick_size <= 0):
                raise DealTickSizeInvalid(
                    f"a positive tick size is required for D3 grid alignment, got "
                    f"{tick_size!r}"
                )
            levels: list[DealLevel] = []
            for lvl in grid.levels:
                quantity = _round_down_lots(lvl.quantity, lot_size)
                if quantity <= 0:
                    raise SizingBelowLot(
                        f"deal grid level {lvl.index} rounds down to 0 lots "
                        f"(quantity {lvl.quantity}, lot size {lot_size}); the whole "
                        f"entry is blocked (C3)"
                    )
                price = (
                    None
                    if lvl.is_market
                    else align_grid_price(lvl.price, tick_size, direction)
                )
                levels.append(
                    DealLevel(
                        index=lvl.index,
                        side=lvl.side,
                        price=price,
                        nominal=lvl.nominal,
                        quantity=quantity,
                        offset_percent=lvl.offset_percent,
                        status=(
                            DealLevelStatus.ACTIVE
                            if lvl.status is GridLevelStatus.ACTIVE
                            else DealLevelStatus.WAITING
                        ),
                        is_market=lvl.is_market,
                    )
                )
            deal = Deal(
                bot_id=bot_id,
                instrument_figi=instrument_figi,
                direction=direction,
                deposit=deposit,
                base_nominal=base_nominal,
                reference_price=reference_price,
                lot_size=lot_size,
                tick_size=tick_size,
                tp_percent=config.exit.take_profit.percent,
                active_limit=grid.active_limit,
                account_id=account_id,
                levels=levels,
            )
            # D2: persist the Deal BEFORE submitting any order, so a crash between
            # the two cannot leave running orders without a Deal to recover.
            await self._store.save(deal)
            await self._submit_ready_levels(deal)
            await self._store.save(deal)
            self._deals[bot_id] = deal
            return deal
        except Exception as exc:  # noqa: BLE001 - B2: a deal-opening failure is surfaced
            # B2: a failed entry is not silent — the bot lifecycle is notified
            # (ERROR) and the reason is observable via ``last_error_for``; the
            # original exception is re-raised so the caller still sees the
            # concrete failure (e.g. SizingBelowLot / DealTickSizeInvalid).
            await self._fail_deal(bot_id, deal, exc)
            raise

    # --- fill plumbing -------------------------------------------------------------

    def _on_order_fill(self, order: InternalOrder, fill: Fill) -> None:
        """Synchronous OrderManager fill listener: queue the reaction (async pump)."""
        if order.bot_id is None:
            return
        self._pending.append((order, fill))

    async def pump(self) -> None:
        """Apply queued fill reactions for all deals (async drain).

        B1: every event is handled independently. A failure in one reaction
        marks exactly that Deal ERROR and notifies the bot lifecycle, then the
        remaining queued events are still processed — a single bad fill cannot
        starve the rest of the batch and no exception escapes the stream's
        ``on_event`` hook.
        """
        events, self._pending = self._pending, []
        for order, fill in events:
            deal = self._deals.get(order.bot_id)
            if deal is None or deal.status is DealStatus.CLOSED or deal.status is DealStatus.ERROR:
                continue
            try:
                if deal.is_tp_intent(order.intent_id):
                    await self._on_tp_fill(deal, order)
                else:
                    await self._on_grid_fill(deal, order, fill)
            except Exception as exc:  # noqa: BLE001 - B1: isolate every event
                # D4/D5 with B1/B2: an unreconcilable reaction marks the Deal
                # ERROR, blocks the bot's new submissions and notifies the bot
                # lifecycle; the stream keeps running and the rest of the batch
                # is still applied.
                await self._fail_deal(order.bot_id, deal, exc)

    async def _on_grid_fill(self, deal: Deal, order: InternalOrder, fill: Fill) -> None:
        level = deal.level_by_order(order.order_id)
        if level is None:
            return  # not a Deal grid order (e.g. stale order id)
        level.filled_quantity += fill.quantity
        if level.filled_quantity >= level.quantity:
            level.status = DealLevelStatus.FILLED
        else:
            level.status = DealLevelStatus.ACTIVE
        if deal.status in (DealStatus.OPENING, DealStatus.CLOSING) and level.index == 0:
            deal.status = DealStatus.OPEN
        # D2.2/D4: every grid fill re-arms the TP from the actual position.
        await self._rearm_tp(deal)
        # D2.3: keep the active-limit count of working grid orders.
        await self._promote_waiting_levels(deal)
        deal.updated_at = utcnow()
        await self._store.save(deal)

    async def _on_tp_fill(self, deal: Deal, order: InternalOrder) -> None:
        pos = self._pm.get(deal.instrument_figi)
        if pos is None or pos.quantity == 0:
            # D2.4: position zero -> cancel the remaining grid orders -> CLOSED.
            await self._close_deal(deal)
            return
        if order.intent_id == deal.tp_intent_id:
            # D2.4: partial fill of the current TP keeps it working.
            return
        # D4 race: an old TP filled while the new one was being re-armed — the
        # current TP quantity is stale; re-arm once from the actual position.
        await self._rearm_tp(deal)

    # --- D4: take-profit re-arm ----------------------------------------------------

    async def _rearm_tp(self, deal: Deal) -> None:
        """Place exactly one TP for the whole current position (D4).

        The new TP is computed and risk-gated BEFORE the working one is
        cancelled (B1): a risk rejection keeps the old TP in place — the
        position is never left uncovered — and only a risk-accepted TP replaces
        it. Quantity (lot-rounded down) and price (average x (1 +- pct/100),
        tick aligned LONG up / SHORT down) come from |PositionManager| facts —
        never the market price. A cancel/placement that cannot be confirmed
        blocks new deal submissions and marks the Deal for reconciliation.
        """
        pos = self._pm.get(deal.instrument_figi)
        if pos is None or pos.quantity == 0:
            await self._close_deal(deal)
            return
        if not _sign_matches(pos.quantity, deal.direction):
            raise DealPositionContradiction(
                f"deal {deal.id}: position quantity {pos.quantity} contradicts "
                f"direction {deal.direction.value}"
            )
        quantity = _round_down_lots(abs(pos.quantity), deal.lot_size)
        if quantity <= 0:
            # Position below one whole lot: there is nothing sellable/buyable in
            # whole lots; close the residual Deal instead of inventing a fraction.
            await self._close_deal(deal)
            return
        raw = deal.tp_price_from_average(pos.average_price)
        price = align_tp_price(raw, deal.tick_size, deal.direction)
        if price <= 0:
            raise DealReconciliationRequired(
                f"deal {deal.id}: take-profit price {price} is not positive"
            )
        deal.tp_rev += 1
        intent = ExecutionIntent(
            intent_id=deal_tp_intent_id(deal.id, deal.tp_rev),
            trade_id="",
            instrument_figi=deal.instrument_figi,
            side=_execute_side(deal.direction),
            order_type=OrderType.LIMIT,
            quantity=quantity,
            limit_price=price,
            reason=f"deal {deal.id} take-profit rev {deal.tp_rev}",
            account_id=deal.account_id,
            bot_id=deal.bot_id,
        )
        try:
            self._rm.check_order(intent)
        except RiskRejected as exc:
            # B1: risk-acceptance comes FIRST — the working TP was not cancelled
            # yet, so a risk rejection leaves the old TAKE-PROFIT in place and
            # the position stays protected while the Deal transitions ERROR.
            raise DealOrderRejected(
                f"deal {deal.id}: take-profit {intent.intent_id} rejected by "
                f"risk manager: {exc}"
            ) from exc
        # B1: only a risk-accepted TP replaces the working one (cancel first,
        # await the confirmation; then submit the new one).
        if deal.tp_order_id is not None:
            order = self._om.get_order(deal.tp_order_id)
            if (
                order is not None
                and order.status not in TERMINAL_STATES
                and order.status is not OrderState.CANCEL_REQUESTED
            ):
                cancelled = await self._om.cancel(deal.tp_order_id)
                if cancelled.status is OrderState.UNKNOWN:
                    raise DealReconciliationRequired(
                        f"deal {deal.id}: take-profit cancel could not be "
                        "confirmed; no second TP is placed and new deal "
                        "submissions are blocked (D4)"
                    )
        tp_order = await self._om.submit(intent)
        if tp_order.status in (OrderState.REJECTED, OrderState.FAILED):
            raise DealOrderRejected(
                f"deal {deal.id}: take-profit rejected: "
                f"{tp_order.reject_info or tp_order.status.value}"
            )
        if tp_order.status is OrderState.UNKNOWN:
            raise DealReconciliationRequired(
                f"deal {deal.id}: take-profit placement could not be confirmed; "
                "new deal submissions are blocked (D4)"
            )
        deal.average_price = pos.average_price
        deal.tp_price = price
        deal.tp_quantity = quantity
        deal.tp_intent_id = tp_order.intent_id
        deal.tp_order_id = tp_order.order_id
        deal.tp_broker_order_id = tp_order.broker_order_id

    # --- partial grid (D2.3) -------------------------------------------------------

    async def _submit_ready_levels(self, deal: Deal) -> None:
        """Submit every ACTIVE level without an order (entry + promotions)."""
        for level in list(deal.levels):
            if level.status is DealLevelStatus.ACTIVE and level.order_id is None:
                await self._submit_level(deal, level)

    async def _submit_level(self, deal: Deal, level: DealLevel) -> None:
        intent = ExecutionIntent(
            intent_id=deal_grid_intent_id(deal.id, level.index),
            trade_id="",
            instrument_figi=deal.instrument_figi,
            side=level.side,
            order_type=OrderType.MARKET if level.is_market else OrderType.LIMIT,
            quantity=level.quantity,
            limit_price=level.price if not level.is_market else None,
            reason=f"deal {deal.id} grid level {level.index}",
            account_id=deal.account_id,
            bot_id=deal.bot_id,
        )
        try:
            self._rm.check_order(intent)
        except RiskRejected as exc:
            # B1: a risk rejection of a grid order is a Deal error (never a
            # silent skip) — the whole entry/re-arm path surfaces it.
            raise DealOrderRejected(
                f"deal {deal.id} grid level {level.index} rejected by risk "
                f"manager: {exc}"
            ) from exc
        order = await self._om.submit(intent)
        if order.status in (OrderState.REJECTED, OrderState.FAILED):
            raise DealOrderRejected(
                f"deal {deal.id} grid level {level.index} rejected: "
                f"{order.reject_info or order.status.value}"
            )
        level.intent_id = order.intent_id
        level.order_id = order.order_id
        level.broker_order_id = order.broker_order_id

    def _working_level_count(self, deal: Deal) -> int:
        count = 0
        for level in deal.levels:
            if level.status is not DealLevelStatus.ACTIVE or level.order_id is None:
                continue
            order = self._om.get_order(level.order_id)
            if order is not None and order.status not in TERMINAL_STATES:
                count += 1
        return count

    async def _promote_waiting_levels(self, deal: Deal) -> None:
        """Promote waiting levels so the working count stays at active_limit."""
        if deal.active_limit is None or deal.status in (DealStatus.CLOSING,):
            return
        while self._working_level_count(deal) < deal.active_limit:
            waiting = next(
                (lvl for lvl in deal.levels if lvl.status is DealLevelStatus.WAITING),
                None,
            )
            if waiting is None:
                break
            waiting.status = DealLevelStatus.ACTIVE
            await self._submit_level(deal, waiting)

    # --- close (D2.4) --------------------------------------------------------------

    async def _close_deal(self, deal: Deal) -> None:
        """Position is zero: cancel the remaining working grid orders, CLOSED."""
        if deal.status in (DealStatus.CLOSED, DealStatus.CLOSING):
            return
        deal.status = DealStatus.CLOSING
        order_ids = [
            level.order_id
            for level in deal.levels
            if level.order_id is not None
            and level.status is not DealLevelStatus.FILLED
        ]
        if deal.tp_order_id is not None:
            order_ids.append(deal.tp_order_id)
        for order_id in order_ids:
            order = self._om.get_order(order_id)
            if (
                order is None
                or order.status in TERMINAL_STATES
                or order.status is OrderState.CANCEL_REQUESTED
            ):
                continue
            cancelled = await self._om.cancel(order_id)
            if cancelled.status is OrderState.UNKNOWN:
                raise DealReconciliationRequired(
                    f"deal {deal.id}: cancelling {order_id} could not be "
                    "confirmed; the Deal stays open for reconciliation"
                )
            level = deal.level_by_order(order_id)
            if level is not None:
                level.status = DealLevelStatus.CANCELLED
        deal.status = DealStatus.CLOSED
        deal.closed_at = utcnow()
        deal.updated_at = utcnow()
        await self._store.save(deal)
        self._deals.pop(deal.bot_id, None)
        self._blocked.discard(deal.bot_id)

    # --- recovery (D5) -------------------------------------------------------------

    async def recover(self, account_id: str, *, reconciliation_ok: bool = True) -> bool:
        """Reconcile persisted non-CLOSED Deals after order/position recovery.

        Returns True when every Deal is resolved (or safely closed); a False
        result marks the offending Deals ERROR and blocks the bots' new deal
        submissions. Recovery reactions are computed from the reconciled
        order/position facts (the fill queue from recovery is discarded — it is
        already applied and deduplicated by the OrderManager).
        """
        self._pending.clear()
        deals = await self._store.list_unclosed()
        safe = True
        for deal in deals:
            try:
                ok = await self._recover_one(deal, account_id, reconciliation_ok)
            except Exception as exc:  # noqa: BLE001 - B2: every recovery failure surfaces
                await self._fail_deal(deal.bot_id, deal, exc)
                self._deals.pop(deal.bot_id, None)
                safe = False
                continue
            if not ok:
                # B2/D5: an unresolved Deal is an ERROR with an observable reason
                # — never a silent skip of a deal the broker facts contradict.
                await self._fail_deal(
                    deal.bot_id,
                    deal,
                    DealReconciliationRequired(
                        f"bot {deal.bot_id}: deal {deal.id} could not be "
                        "reconciled to the broker facts (D5); new submissions are "
                        "blocked until an explicit reconciliation"
                    ),
                )
                self._deals.pop(deal.bot_id, None)
                safe = False
                continue
            self._deals[deal.bot_id] = deal
            deal.updated_at = utcnow()
            await self._store.save(deal)
        return safe

    async def _recover_one(
        self, deal: Deal, account_id: str, reconciliation_ok: bool
    ) -> bool:
        """Bring one Deal in line with the reconciled facts (see recover())."""
        rearm = False
        entry_filled = False
        for level in deal.levels:
            if level.status is DealLevelStatus.WAITING:
                continue  # never submitted; stays planned (no blind recreation)
            if level.order_id is None:
                return False  # ACTIVE level without an order: unknown state
            order = self._om.get_order(level.order_id)
            if order is None:
                return False
            if order.status is OrderState.UNKNOWN:
                return False
            if order.status is OrderState.FILLED:
                level.status = DealLevelStatus.FILLED
                level.filled_quantity = order.filled_quantity or level.quantity
                if level.index == 0:
                    entry_filled = True
                rearm = True
            elif order.status is OrderState.PARTIALLY_FILLED:
                level.status = DealLevelStatus.ACTIVE
                level.filled_quantity = order.filled_quantity
                if level.index == 0:
                    entry_filled = True
                rearm = True
            elif order.status in (OrderState.SUBMITTED, OrderState.WORKING):
                if level.status is DealLevelStatus.CANCELLED:
                    level.status = DealLevelStatus.ACTIVE
                # D5: a working grid order stays in place (no blind recreation).
            elif deal.status is DealStatus.CLOSING:
                level.status = DealLevelStatus.CANCELLED
            else:
                # CANCELLED/REJECTED/FAILED mid-deal contradicts the deal:
                # explicit ERROR, no silent continuation.
                return False

        if deal.status is DealStatus.OPENING and entry_filled:
            deal.status = DealStatus.OPEN

        if deal.status is DealStatus.CLOSING:
            all_terminal = True
            for level in deal.levels:
                if level.order_id is None:
                    continue
                order = self._om.get_order(level.order_id)
                if order is None or order.status not in TERMINAL_STATES:
                    all_terminal = False
            if all_terminal:
                deal.status = DealStatus.CLOSED
                deal.closed_at = utcnow()
                self._deals.pop(deal.bot_id, None)
                self._blocked.discard(deal.bot_id)
                return True
            return False

        pos = self._pm.get(deal.instrument_figi)
        if pos is None or pos.quantity == 0:
            if deal.status is DealStatus.OPENING:
                return True  # no fill yet, no position — nothing to re-arm
            # Position zero: the TP filled (or the deal is otherwise done).
            await self._close_deal(deal)
            return True
        if deal.status is DealStatus.OPENING:
            return False  # a position exists but the entry was never filled
        if not _sign_matches(pos.quantity, deal.direction):
            return False
        tp_order = (
            self._om.get_order(deal.tp_order_id) if deal.tp_order_id is not None else None
        )
        if tp_order is not None and tp_order.status is OrderState.UNKNOWN:
            return False
        if tp_order is not None and tp_order.status is OrderState.FILLED:
            return False  # TP filled but a position remains: contradiction
        if rearm:
            # D5: a grid order the broker reports filled re-arms the TP (D4).
            await self._rearm_tp(deal)
        elif tp_order is None or tp_order.status in (
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
        ):
            if not reconciliation_ok:
                return False  # no TP placement before a successful reconciliation
            await self._rearm_tp(deal)  # place the missing TP once
        return True
