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

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal

from app.brokers.base import BrokerStopOrder, BrokerStopOrderRequest, StopOrderStatus
from app.models.enums import OrderSide, OrderType
from app.strategies.config import Direction, StopLossConfig, StrategyConfig
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
    DealStopExecuted,
    DealStore,
    DealTickSizeInvalid,
    align_grid_price,
    align_stop_price,
    align_tp_price,
    deal_grid_intent_id,
    deal_stop_intent_id,
    deal_tp_intent_id,
    utcnow,
)
from app.trading.domain import (
    TERMINAL_STATES,
    ExecutionIntent,
    Fill,
    InternalOrder,
    OrderState,
    PositionUpdate,
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
        # MVP-6.16 E3: broker-neutral callback after a stop-loss closes a deal;
        # receives (bot_id, stop_bot_after). Production stops the bot and
        # persists the stop reason when stop_bot_after is True.
        on_stop_loss: Callable[[int, bool], Awaitable[None]] | None = None,
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
        self._on_stop_loss = on_stop_loss
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
            # MVP-6.16 E1/E3: capture the simple stop contract on the Deal at
            # open. sl_offset is the grid-ladder component
            # ((last level offset - level 0 offset)); the stop itself is armed
            # only when the whole grid is filled (see _rearm_stop).
            sl = config.exit.stop_loss
            if isinstance(sl, StopLossConfig):
                deal.sl_percent = sl.percent
                deal.stop_bot_after = sl.stop_bot_after
                if levels:
                    deal.sl_offset = Decimal(
                        str(levels[-1].offset_percent - levels[0].offset_percent)
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
        # MVP-6.16 E2: reconcile armed stops with broker facts after the fill
        # batch — a stop execution arrives as a REST fact, never as a stream
        # fill, so it is only observable here (GetStopOrders + positions).
        await self.check_stop_orders()

    async def _on_grid_fill(self, deal: Deal, order: InternalOrder, fill: Fill) -> None:
        level = deal.level_by_order(order.order_id)
        if level is None:
            return  # not a Deal grid order (e.g. stale order id)
        # MVP-6.16 E1: P0 = actual average fill price of the level-0 order;
        # accumulate the weighted average across partial fills (single full
        # fill -> the fill price itself).
        if level.index == 0:
            prev_filled = level.filled_quantity
            if deal.p0_price is None:
                deal.p0_price = fill.price
            else:
                total = prev_filled + fill.quantity
                if total > 0:
                    deal.p0_price = (
                        deal.p0_price * prev_filled + fill.price * fill.quantity
                    ) / total
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
        # MVP-6.16 E1: the stop becomes active only after ALL grid levels are
        # filled; every later position change re-arms it (see _rearm_stop).
        if self._grid_assembled(deal):
            await self._rearm_stop(deal)
        deal.updated_at = utcnow()
        await self._store.save(deal)

    async def _on_tp_fill(self, deal: Deal, order: InternalOrder) -> None:
        pos = self._pm.get(deal.instrument_figi)
        if pos is None or pos.quantity == 0:
            # D2.4: position zero -> cancel the remaining grid orders -> CLOSED.
            await self._close_deal(deal, close_reason="take_profit")
            return
        if order.intent_id == deal.tp_intent_id:
            # D2.4: partial fill of the current TP keeps it working; the stop
            # still follows the reduced position (E2 re-arm on position change).
            if self._grid_assembled(deal):
                await self._rearm_stop(deal)
            return
        # D4 race: an old TP filled while the new one was being re-armed — the
        # current TP quantity is stale; re-arm once from the actual position.
        await self._rearm_tp(deal)
        if self._grid_assembled(deal):
            await self._rearm_stop(deal)

    # --- D4: take-profit re-arm ----------------------------------------------------

    async def _rearm_tp(self, deal: Deal) -> None:
        """Place exactly one TP for the whole current position (D4).

        The new TP is computed and risk-gated BEFORE the working one is
        cancelled (B1): a risk rejection keeps the old TP in place — the
        position is never left uncovered — and only a risk-accepted TP replaces
        it. Quantity (lot-rounded down) and price (average x (1 +- pct/100),
        tick aligned LONG up / SHORT down) come from |PositionManager| facts —
        never the market price. After the cancel the position is re-read (B3):
        the old TP may have filled (fully or partly) while its cancel was in
        flight, and the new TP is rebuilt from the ACTUAL post-cancel facts
        (never larger than the position), risk-gated again. A cancel/placement
        that cannot be confirmed blocks new deal submissions and marks the Deal
        for reconciliation.
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
        # B1: risk-acceptance comes FIRST — the working TP is not cancelled yet,
        # so a rejection leaves the old TP in place and the position stays
        # protected while the Deal transitions ERROR.
        intent = self._tp_intent(deal, quantity, price)
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
                # B3: the old TP can fill (fully or partly) while its cancel is
                # in flight — the position is the source of truth and the new TP
                # must never exceed it. Re-read and rebuild when facts changed.
                pos = self._pm.get(deal.instrument_figi)
                if pos is None or pos.quantity == 0:
                    await self._close_deal(deal)
                    return
                if not _sign_matches(pos.quantity, deal.direction):
                    raise DealPositionContradiction(
                        f"deal {deal.id}: position quantity {pos.quantity} "
                        f"contradicts direction {deal.direction.value}"
                    )
                fresh_quantity = _round_down_lots(abs(pos.quantity), deal.lot_size)
                if fresh_quantity <= 0:
                    await self._close_deal(deal)
                    return
                fresh_raw = deal.tp_price_from_average(pos.average_price)
                fresh_price = align_tp_price(fresh_raw, deal.tick_size, deal.direction)
                if fresh_price <= 0:
                    raise DealReconciliationRequired(
                        f"deal {deal.id}: take-profit price {fresh_price} is not positive"
                    )
                if fresh_quantity != quantity or fresh_price != price:
                    intent = self._tp_intent(deal, fresh_quantity, fresh_price)
                    quantity, price = fresh_quantity, fresh_price
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

    def _tp_intent(self, deal: Deal, quantity: Decimal, price: Decimal) -> ExecutionIntent:
        """Build the next TP intent (new tp_rev) and risk-gate it (B1/D7).

        The intent id embeds the Deal id and the monotonically increasing
        revision, so every attempt has a deterministic id. ``check_order`` is
        called BEFORE any cancel: a |RiskRejected| raises |DealOrderRejected|
        and the old TP keeps working (D7 exempts the reducing TP from the
        growth limits, so a rejection here is an emergency-stop / permission
        case, never a size-limit case).
        """
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
            raise DealOrderRejected(
                f"deal {deal.id}: take-profit {intent.intent_id} rejected by "
                f"risk manager: {exc}"
            ) from exc
        return intent

    # --- MVP-6.16 E1/E2: simple stop-loss lifecycle ---------------------------

    def _grid_assembled(self, deal: Deal) -> bool:
        """E1: whether every grid level of the Deal has been filled."""
        return all(level.status is DealLevelStatus.FILLED for level in deal.levels)

    @staticmethod
    def _stop_idempotency_key(deal_id: int, rev: int) -> str:
        """Stable UUID idempotency key for one stop revision (E2).

        T-Invest requires a UUID; a deterministic UUID5 per (deal, rev) lets a
        retry of the same placement return the already-placed order instead of
        creating a second stop.
        """
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"veles-deal-{deal_id}-stop-{rev}"))

    def _stop_intent(self, deal: Deal, quantity: Decimal) -> ExecutionIntent:
        """Build the risk-gate intent for a stop close (E2/D7).

        The stop reduces the position, so the growth limits are exempt; the
        emergency-stop / quantity / instrument-permission checks still apply.
        The intent id embeds the Deal id and the monotonically increasing stop
        revision; the broker stop order itself carries the same revision in its
        idempotency key.
        """
        deal.sl_rev += 1
        intent = ExecutionIntent(
            intent_id=deal_stop_intent_id(deal.id, deal.sl_rev),
            trade_id="",
            instrument_figi=deal.instrument_figi,
            side=_execute_side(deal.direction),
            order_type=OrderType.MARKET,
            quantity=quantity,
            reason=f"deal {deal.id} stop-loss rev {deal.sl_rev}",
            account_id=deal.account_id,
            bot_id=deal.bot_id,
        )
        try:
            self._rm.check_order(intent)
        except RiskRejected as exc:
            raise DealOrderRejected(
                f"deal {deal.id}: stop-loss {intent.intent_id} rejected by "
                f"risk manager: {exc}"
            ) from exc
        return intent

    async def _broker_stops(self, deal: Deal) -> list[BrokerStopOrder]:
        """B1: read the broker's stop orders for the Deal's window.

        Without an explicit status filter T-Invest ``GetStopOrders`` returns
        only ACTIVE orders, so an EXECUTED stop would look "missing". The
        window — from the Deal's opening (its stop can only be placed after)
        to now — asks for executed/cancelled/expired history without pulling
        the whole account history.
        """
        return await self._om.broker.get_stop_orders(
            deal.account_id, from_=deal.created_at, to=utcnow()
        )

    async def _broker_position_quantity(self, deal: Deal) -> Decimal:
        """B1: the instrument quantity the broker reports (GetPortfolio)."""
        positions = await self._om.broker.get_open_positions(deal.account_id)
        pos = next(
            (p for p in positions if p.instrument_figi == deal.instrument_figi), None
        )
        return pos.quantity if pos is not None else Decimal("0")

    async def _confirm_stop_cancelled(self, deal: Deal) -> None:
        """Cancel the working stop order and confirm the outcome (E2).

        An ACTIVE stop after the cancel (or an unknown state) raises: a second
        stop is never placed while the old one may still be working. An EXECUTED
        outcome is not a confirmed cancel — the caller re-reads the position and
        resolves the deal from the broker facts. A cancel that fails while the
        stop is already gone is not a failure: the state lookup decides.
        """
        if deal.sl_order_id is None:
            return
        try:
            await self._om.broker.cancel_stop_order(deal.sl_order_id, deal.account_id)
        except Exception:  # noqa: BLE001 - the state lookup confirms the outcome
            pass
        orders = await self._broker_stops(deal)
        ours = [o for o in orders if o.order_id == deal.sl_order_id]
        if not ours:
            return  # gone: cancelled (or executed; the caller re-reads)
        if ours[0].status is StopOrderStatus.EXECUTED:
            # Not an unknown outcome: the stop was consumed while the cancel
            # was in flight and the caller must resolve the close from facts.
            raise DealStopExecuted(
                f"deal {deal.id}: stop {deal.sl_order_id} executed while its "
                "cancel was in flight (E2)"
            )
        if ours[0].status not in (StopOrderStatus.CANCELLED, StopOrderStatus.EXPIRED):
            raise DealReconciliationRequired(
                f"deal {deal.id}: stopping of {deal.sl_order_id} "
                f"could not be confirmed (status {ours[0].status.value}); no "
                "second stop is placed and new deal submissions are blocked (E2)"
            )

    async def _rearm_stop(self, deal: Deal) -> None:
        """E1/E2: place exactly one stop covering the whole current position.

        Mirrors the D4 TP re-arm: the new stop is computed and risk-gated FIRST
        (a rejection keeps the working stop in place — the position is never
        left unprotected by a failed re-arm), then the old stop is cancelled and
        confirmed, the position is re-read (the old stop may have executed while
        its cancel was in flight) and only a fresh stop over the ACTUAL
        post-cancel position is placed. The trigger is P0 x (1 -+ (sl_offset +
        sl_percent)/100) (|simple_stop_level|), tick-aligned LONG up / SHORT
        down (|align_stop_price|, the safe/early-trigger direction); the
        quantity is the whole position rounded down to whole lots.
        """
        if deal.sl_percent is None:
            return
        pos = self._pm.get(deal.instrument_figi)
        if pos is None or pos.quantity == 0:
            # D4 race: the exit (TP fill or executed stop) may have already
            # been resolved and persisted while the re-arm re-read the
            # position — nothing left to protect.
            if deal.status in (DealStatus.CLOSED, DealStatus.CLOSING):
                return
            # B1: a zero position with an armed deal is not closed silently —
            # the exit is resolved from explicit facts (TP fill / executed
            # stop) and never invented here; an unreconciliable state is ERROR.
            raise DealReconciliationRequired(
                f"deal {deal.id}: no position to protect; the close reason "
                "cannot be determined from a zero position (E2)"
            )
        if not _sign_matches(pos.quantity, deal.direction):
            raise DealPositionContradiction(
                f"deal {deal.id}: position quantity {pos.quantity} contradicts "
                f"direction {deal.direction.value}"
            )
        quantity = _round_down_lots(abs(pos.quantity), deal.lot_size)
        if quantity <= 0:
            # B1: a position below one whole lot cannot be covered by a stop
            # in whole lots — explicit ERROR, no silent close (E2).
            raise DealReconciliationRequired(
                f"deal {deal.id}: position {pos.quantity} is below one whole "
                f"lot {deal.lot_size}; a stop cannot be armed and the close "
                "reason cannot be determined (E2)"
            )
        if deal.p0_price is None:
            raise DealReconciliationRequired(
                f"deal {deal.id}: the P0 fill price is not known; the stop "
                "level cannot be computed (E1)"
            )
        raw = deal.sl_price_from_p0()
        price = align_stop_price(raw, deal.tick_size, deal.direction)
        if price <= 0:
            raise DealReconciliationRequired(
                f"deal {deal.id}: stop price {price} is not positive"
            )
        # B1: risk-acceptance comes FIRST — the working stop is not cancelled
        # yet, so a rejection leaves it in place and the position stays protected.
        self._stop_intent(deal, quantity)
        if deal.sl_order_id is not None:
            try:
                await self._confirm_stop_cancelled(deal)
            except DealStopExecuted:
                # E2: the old stop executed while its cancel was in flight —
                # resolve the close from the broker facts (position +
                # GetStopOrders); never place a second stop.
                await self._on_stop_executed(deal)
                return
            # E2 B3-equivalent: re-read the position after the cancel.
            pos = self._pm.get(deal.instrument_figi)
            if pos is None or pos.quantity == 0:
                raise DealReconciliationRequired(
                    f"deal {deal.id}: the position is flat after the stop "
                    f"cancel (stop {deal.sl_order_id}); the close reason "
                    "cannot be determined (E2)"
                )
            if not _sign_matches(pos.quantity, deal.direction):
                raise DealPositionContradiction(
                    f"deal {deal.id}: position quantity {pos.quantity} "
                    f"contradicts direction {deal.direction.value}"
                )
            fresh_quantity = _round_down_lots(abs(pos.quantity), deal.lot_size)
            if fresh_quantity <= 0:
                raise DealReconciliationRequired(
                    f"deal {deal.id}: position {pos.quantity} is below one "
                    f"whole lot {deal.lot_size}; the stop cannot be re-armed "
                    "after the cancel (E2)"
                )
            if fresh_quantity != quantity:
                # E2: the re-read position differs from the pre-cancel one —
                # gate the actual volume through Risk before placing it.
                self._stop_intent(deal, fresh_quantity)
                quantity = fresh_quantity
        stop = await self._om.broker.place_stop_order(
            BrokerStopOrderRequest(
                instrument_figi=deal.instrument_figi,
                side=_execute_side(deal.direction),
                quantity=quantity,
                stop_price=price,
                account_id=deal.account_id,
                idempotency_key=self._stop_idempotency_key(deal.id, deal.sl_rev),
            )
        )
        if stop.status is StopOrderStatus.UNKNOWN:
            raise DealReconciliationRequired(
                f"deal {deal.id}: stop placement could not be confirmed; new "
                "deal submissions are blocked (E2)"
            )
        deal.sl_quantity = quantity
        deal.sl_price = price
        deal.sl_order_id = stop.order_id

    async def check_stop_orders(self) -> None:
        """E2: reconcile armed stops with broker facts (called at pump() end).

        For every armed open Deal the broker's stop orders are fetched (one
        GetStopOrders per account per batch — T-Invest rate limits) and matched
        by broker stop order id: an EXECUTED stop closes the Deal (the position
        is confirmed flat at the broker first; a remaining position is a
        contradiction -> ERROR), an ACTIVE stop stays, a missing or cancelled
        stop is reconciled against the broker position before any re-arm (B1:
        a zero position cannot be correlated -> ERROR, a real position re-arms
        once), any unknown state blocks the bot (ERROR).
        """
        armed = [
            deal
            for deal in self._deals.values()
            if deal.sl_percent is not None
            and deal.sl_order_id is not None
            and deal.status not in (DealStatus.CLOSED, DealStatus.ERROR, DealStatus.CLOSING)
        ]
        if not armed:
            return
        windows: dict[str, datetime] = {}
        for deal in armed:
            oldest = windows.get(deal.account_id)
            if oldest is None or deal.created_at < oldest:
                windows[deal.account_id] = deal.created_at
        now = utcnow()
        stops_by_account: dict[str, list[BrokerStopOrder]] = {}
        failed: dict[str, Exception] = {}
        for account_id, from_ in windows.items():
            try:
                stops_by_account[account_id] = await self._om.broker.get_stop_orders(
                    account_id, from_=from_, to=now
                )
            except Exception as exc:  # noqa: BLE001 - tunneled as a Deal failure
                failed[account_id] = exc
        for deal in armed:
            if deal.account_id in failed:
                await self._fail_deal(deal.bot_id, deal, failed[deal.account_id])
                continue
            broker_stops = stops_by_account[deal.account_id]
            ours = [o for o in broker_stops if o.order_id == deal.sl_order_id]
            if ours and ours[0].status is StopOrderStatus.ACTIVE:
                continue
            if not ours or ours[0].status is StopOrderStatus.CANCELLED:
                # E2/B1: an absent (or externally cancelled) stop is an unknown
                # outcome, never a reason to place a new one. The broker's
                # position is reconciled first: zero -> the close cannot be
                # correlated to this Deal (ERROR); a real position -> re-arm.
                try:
                    if await self._broker_position_quantity(deal) == 0:
                        raise DealReconciliationRequired(
                            f"deal {deal.id}: stop {deal.sl_order_id} is "
                            f"{'missing at' if not ours else 'cancelled at'} the "
                            "broker and the broker position is flat; the close "
                            "cannot be correlated to the deal (E2)"
                        )
                    if self._grid_assembled(deal):
                        deal.sl_order_id = None  # the broker no longer knows it
                        await self._rearm_stop(deal)
                        continue
                    raise DealReconciliationRequired(
                        f"deal {deal.id}: armed stop {deal.sl_order_id} is "
                        "missing at the broker and the grid is not assembled; "
                        "reconciliation required (E2)"
                    )
                except Exception as exc:  # noqa: BLE001 - B1: isolate the event
                    await self._fail_deal(deal.bot_id, deal, exc)
                continue
            if ours[0].status is StopOrderStatus.EXECUTED:
                try:
                    await self._on_stop_executed(deal)
                except Exception as exc:  # noqa: BLE001 - B1: isolate the event
                    await self._fail_deal(deal.bot_id, deal, exc)
                continue
            await self._fail_deal(
                deal.bot_id,
                deal,
                DealReconciliationRequired(
                    f"deal {deal.id}: stop {deal.sl_order_id} is in state "
                    f"{ours[0].status.value} which cannot be reconciled (E2)"
                ),
            )

    async def _on_stop_executed(self, deal: Deal) -> None:
        """E2: a broker stop executed — confirm the position is flat, then close.

        The executed stop is a broker fact, not an OrderManager fill: the
        broker position is the source of truth. Zero position -> update the
        PositionManager, cancel the TP and close the Deal with
        ``close_reason="stop_loss"``; a remaining position contradicts the
        execution and blocks the bot (ERROR).
        """
        positions = await self._om.broker.get_open_positions(deal.account_id)
        pos = next((p for p in positions if p.instrument_figi == deal.instrument_figi), None)
        if pos is not None and pos.quantity != 0:
            raise DealPositionContradiction(
                f"deal {deal.id}: stop {deal.sl_order_id} is EXECUTED but the "
                f"broker still reports position {pos.quantity} for "
                f"{deal.instrument_figi}; reconciliation required (E2)"
            )
        self._pm.apply_position_update(
            PositionUpdate(
                instrument_figi=deal.instrument_figi,
                quantity=Decimal("0"),
                current_price=pos.current_price if pos is not None else None,
            )
        )
        await self._close_deal(deal, close_reason="stop_loss")

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

    async def _close_deal(
        self, deal: Deal, *, close_reason: str | None = None
    ) -> None:
        """Position is zero: cancel the remaining working orders, CLOSED.

        ``close_reason`` is ``"stop_loss"`` when the Deal closes after the
        broker stop executed (E2); that close needs no stop cancel (the stop is
        already consumed). Every other close cancels the Deal-owned stop first
        and requires the cancel to be confirmed (E2: a stop must never survive
        a closed Deal).
        """
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
        if (
            deal.sl_percent is not None
            and deal.sl_order_id is not None
            and close_reason != "stop_loss"
        ):
            try:
                await self._confirm_stop_cancelled(deal)
            except DealStopExecuted:
                # The stop was consumed while its cancel was in flight: the
                # zero position is the stop's result, not the TP's (E2).
                close_reason = "stop_loss"
        deal.status = DealStatus.CLOSED
        deal.close_reason = close_reason
        deal.closed_at = utcnow()
        deal.updated_at = utcnow()
        await self._store.save(deal)
        self._deals.pop(deal.bot_id, None)
        self._blocked.discard(deal.bot_id)
        if close_reason == "stop_loss" and self._on_stop_loss is not None:
            # E3/B2: the CLOSED state is already persisted, but a failing
            # stop-bot callback must not leave the bot running against
            # stop_bot_after — surface it through the B2 error path.
            try:
                await self._on_stop_loss(deal.bot_id, deal.stop_bot_after is True)
            except Exception as exc:  # noqa: BLE001 - B2: error, never a silent swallow
                await self._fail_deal(deal.bot_id, deal, exc)

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
            if deal.status is DealStatus.CLOSED:
                # `_recover_one` closed it (position zero / TP fully filled
                # during the re-arm cancel) — `_close_deal` already popped it
                # and persisted the CLOSED state; do not re-register a closed
                # Deal as active (it would block the next entry).
                self._deals.pop(deal.bot_id, None)
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
                    if deal.p0_price is None and order.average_fill_price > 0:
                        deal.p0_price = order.average_fill_price
                rearm = True
            elif order.status is OrderState.PARTIALLY_FILLED:
                level.status = DealLevelStatus.ACTIVE
                level.filled_quantity = order.filled_quantity
                if level.index == 0:
                    entry_filled = True
                    if deal.p0_price is None and order.average_fill_price > 0:
                        deal.p0_price = order.average_fill_price
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

        # MVP-6.16 E2/D5: reconcile the armed stop with broker facts BEFORE the
        # position checks — a stop execution is a REST fact, never a stream
        # fill, so only GetStopOrders can reveal it. An executed stop closes
        # the Deal with close_reason="stop_loss"; a missing or cancelled stop
        # is re-armed once below (assembled grid only); an unknown state is an
        # explicit unresolved Deal (ERROR).
        if deal.sl_percent is not None and deal.sl_order_id is not None:
            try:
                broker_stops = await self._broker_stops(deal)
            except Exception as exc:  # noqa: BLE001 - unknown broker state
                raise DealReconciliationRequired(
                    f"deal {deal.id}: stop orders could not be read during "
                    f"recovery: {exc}"
                ) from exc
            ours = [o for o in broker_stops if o.order_id == deal.sl_order_id]
            if ours and ours[0].status is StopOrderStatus.EXECUTED:
                await self._on_stop_executed(deal)
                return True
            if not ours:
                # B1: missing at the broker is an unknown outcome, not a free
                # pass to re-arm. A flat broker position is explainable only
                # by a known TP fill (OrderManager fact); otherwise the close
                # cannot be correlated with this Deal -> explicit ERROR.
                tp_order = (
                    self._om.get_order(deal.tp_order_id) if deal.tp_order_id is not None else None
                )
                tp_filled = tp_order is not None and tp_order.status is OrderState.FILLED
                if not tp_filled and await self._broker_position_quantity(deal) == 0:
                    raise DealReconciliationRequired(
                        f"deal {deal.id}: stop {deal.sl_order_id} is missing at "
                        "the broker and the broker position is flat; the close "
                        "cannot be correlated to the deal (E2)"
                    )
                deal.sl_order_id = None
            elif ours[0].status in (
                StopOrderStatus.CANCELLED,
                StopOrderStatus.EXPIRED,
            ):
                deal.sl_order_id = None
            elif ours[0].status is not StopOrderStatus.ACTIVE:
                return False  # UNKNOWN state -> explicit ERROR

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
            await self._close_deal(deal, close_reason="take_profit")
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
        # MVP-6.16 E2/D5: an ACTIVE stop is kept as-is (E2 "активная остаётся");
        # it is re-armed only when the position (or the P0/level facts used for
        # its price) changed since it was armed. A missing stop is placed once.
        # A change is detected against the facts recorded at the last arm
        # (sl_quantity / sl_price) — never by re-placing on every restart.
        if (
            deal.sl_percent is not None
            and self._grid_assembled(deal)
            and reconciliation_ok
        ):
            if deal.sl_order_id is None:
                await self._rearm_stop(deal)
            else:
                # The TP re-arm above may have consumed the position (B3) and
                # closed the Deal; re-read before touching the stop.
                pos = self._pm.get(deal.instrument_figi)
                if pos is None or pos.quantity == 0:
                    return True
                current = _round_down_lots(abs(pos.quantity), deal.lot_size)
                if current <= 0:
                    # B1: a position below one whole lot cannot be covered by
                    # a stop in whole lots — explicit ERROR, no silent close.
                    return False
                else:
                    expected = align_stop_price(
                        deal.sl_price_from_p0(), deal.tick_size, deal.direction
                    )
                    if (
                        deal.sl_quantity is None
                        or current != deal.sl_quantity
                        or deal.sl_price is None
                        or expected != deal.sl_price
                    ):
                        await self._rearm_stop(deal)
        return True
