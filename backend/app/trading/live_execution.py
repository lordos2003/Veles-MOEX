"""Live execution composition / startup gate (MVP-6.3).

``LiveExecutionService`` is the production composition root that wires the
durable store, the broker-neutral managers and the recovery coordinator
together. On startup it runs ``recover()``; live execution is only allowed once
recovery returns ``SAFE``. When recovery returns ``BLOCKED``, ``submit()`` is
refused so unsafe new execution cannot resume.
"""

from __future__ import annotations

from app.trading.domain import ExecutionIntent, InternalOrder
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.recovery import LiveRecoveryCoordinator, RecoveryResult
from app.trading.state import LiveStateStore


class LiveExecutionBlocked(RuntimeError):
    """Raised when live execution is attempted before a safe recovery."""


class LiveExecutionService:
    """Gates live execution behind a successful startup/recovery reconciliation."""

    def __init__(
        self,
        broker,
        store: LiveStateStore,
        order_manager: OrderManager,
        position_manager: PositionManager,
        account_id: str | None = None,
        transport=None,
    ) -> None:
        self._broker = broker
        self._order_manager = order_manager
        self._coordinator = LiveRecoveryCoordinator(
            store, order_manager, position_manager, broker
        )
        self._account_id = account_id
        self._safe = False
        self._session_owner = None
        self._stream_transport = transport
        self._stream_manager = None

    @property
    def can_execute(self) -> bool:
        """True once a SAFE recovery has completed."""
        return self._safe

    @property
    def coordinator(self) -> LiveRecoveryCoordinator:
        return self._coordinator

    async def start(self) -> RecoveryResult:
        """Run reconciliation and gate execution according to its outcome."""
        account_id = self._account_id
        if account_id is None:
            accounts = await self._broker.get_accounts()
            if not accounts:
                raise LiveExecutionBlocked("no broker account available for recovery")
            account_id = accounts[0].account_id
        self._account_id = account_id
        result = await self._coordinator.recover(account_id)
        self._safe = result.safe
        return result

    async def submit(self, intent: ExecutionIntent) -> InternalOrder:
        """Submit an intent only after a SAFE recovery."""
        if not self._safe:
            raise LiveExecutionBlocked("live execution blocked until recovery succeeds")
        return await self._order_manager.submit(intent)

    def build_stream_manager(self, transport):
        """Compose an OrderStateStream manager whose reconnect runs full recovery.

        On reconnect the stream manager runs unary recovery, then this recovery
        hook (durable reconciliation); live events are dispatched only when it is
        SAFE, otherwise they are paused.
        """
        from app.brokers.tinvest_streams import TInvestStreamManager

        return TInvestStreamManager(
            self._broker,
            transport,
            self._order_manager,
            self._account_id,
            recovery=self._stream_recovery,
        )

    async def _stream_recovery(self) -> bool:
        """Full recovery used as the reconnect gate. Returns True when SAFE."""
        account_id = self._account_id
        if account_id is None:
            accounts = await self._broker.get_accounts()
            account_id = accounts[0].account_id if accounts else None
        result = await self._coordinator.recover(account_id)
        self._safe = result.safe
        return result.safe

    async def run_stream_forever(self) -> None:
        """Run the production OrderStateStream live runtime until :meth:`shutdown`.

        Creates the T-Invest WebSocket transport (unless injected) and runs the
        stream manager, whose reconnect path already runs unary recovery then the
        full durable recovery gate before dispatching live events.
        """
        if not self._safe:
            raise LiveExecutionBlocked(
                "cannot start live stream before a SAFE recovery"
            )
        if self._stream_transport is None:
            self._stream_transport = await self._build_transport()
        self._stream_manager = self.build_stream_manager(self._stream_transport)
        await self._stream_manager.run()

    async def shutdown(self) -> None:
        """Stop the live stream and close the session/transport."""
        if self._stream_manager is not None:
            self._stream_manager.stop()
        if self._stream_transport is not None:
            try:
                await self._stream_transport.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass
        session = self._session_owner
        if session is not None:
            try:
                await session.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass

    async def _build_transport(self):
        from app.brokers.tinvest_stream_transport import build_stream_transport
        from app.core.config import get_settings

        settings = get_settings()
        return build_stream_transport(
            settings.tinvest_stream_url, settings.tinvest_token
        )


def build_live_service() -> LiveExecutionService:
    """Compose a live execution service from application settings.

    Uses the configured T-Invest adapter and the SQLAlchemy-backed durable state
    store. The caller owns the returned service; ``shutdown()`` closes the
    underlying session.
    """
    from app.brokers import TInvestAdapter
    from app.core.db import SessionLocal
    from app.persistence.execution_state import SqlAlchemyLiveStateStore

    broker = TInvestAdapter()
    session = SessionLocal()
    store = SqlAlchemyLiveStateStore(session)
    order_manager = OrderManager(broker)
    position_manager = order_manager.positions()
    service = LiveExecutionService(broker, store, order_manager, position_manager)
    service._session_owner = session
    return service
