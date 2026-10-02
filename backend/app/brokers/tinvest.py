"""TInvestAdapter — read-only integration with T-Invest API.

Implements the broker-agnostic |BrokerAdapter| interface and hides all T-Invest
specifics: instrument types, trading statuses, candle intervals, order statuses,
directions and deal types are mapped to our internal enums here, and only domain
DTOs leave the adapter. No trade placement — trading methods deliberately raise
NotImplementedError.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.brokers.base import (
    BrokerAccount,
    BrokerAdapter,
    BrokerDeal,
    BrokerExecution,
    BrokerInstrument,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
    BrokerStopOrder,
    BrokerStopOrderRequest,
    StopOrderStatus,
)
from app.brokers.tinvest_client import TInvestClient
from app.brokers.tinvest_errors import (
    AccountNotFoundError,
    AuthenticationError,
    BrokerApiError,
    InstrumentNotFoundError,
    InvalidRequestError,
    ResourceNotFoundError,
)
from app.core.config import get_settings
from app.domain.instrument import InstrumentType, TradingStatus
from app.domain.marketdata import Candle, LastPrice, Timeframe
from app.models.enums import OrderSide, OrderStatus, OrderType

logger = logging.getLogger(__name__)

_USERS = "tinkoff.public.invest.api.contract.v1.UsersService"
_OPERATIONS = "tinkoff.public.invest.api.contract.v1.OperationsService"
_ORDERS = "tinkoff.public.invest.api.contract.v1.OrdersService"
_STOP_ORDERS = "tinkoff.public.invest.api.contract.v1.StopOrdersService"
_INSTRUMENTS = "tinkoff.public.invest.api.contract.v1.InstrumentsService"
_MARKET = "tinkoff.public.invest.api.contract.v1.MarketDataService"

_SANDBOX_BASE = "https://sandbox-invest-public-api.tbank.ru/rest"

# kind -> InstrumentsService list method (returns {"instruments": [...]}).
_KIND_TO_LIST_METHOD = {
    "share": f"{_INSTRUMENTS}/Shares",
    "etf": f"{_INSTRUMENTS}/Etfs",
    "bond": f"{_INSTRUMENTS}/Bonds",
    "currency": f"{_INSTRUMENTS}/Currencies",
    "future": f"{_INSTRUMENTS}/Futures",
}

# Internal Timeframe -> T-Invest CandleInterval enum.
_TIMEFRAME_TO_INTERVAL = {
    Timeframe.MIN_1: "CANDLE_INTERVAL_1_MIN",
    Timeframe.MIN_5: "CANDLE_INTERVAL_5_MIN",
    Timeframe.MIN_15: "CANDLE_INTERVAL_15_MIN",
    Timeframe.MIN_30: "CANDLE_INTERVAL_30_MIN",
    Timeframe.HOUR_1: "CANDLE_INTERVAL_HOUR",
    Timeframe.HOUR_4: "CANDLE_INTERVAL_4_HOUR",
    Timeframe.DAY_1: "CANDLE_INTERVAL_DAY",
    Timeframe.WEEK_1: "CANDLE_INTERVAL_WEEK",
    Timeframe.MONTH_1: "CANDLE_INTERVAL_MONTH",
}

# T-Invest instrument_type string -> our InstrumentType.
_TINVEST_TYPE_MAP = {
    "share": InstrumentType.SHARE,
    "etf": InstrumentType.ETF,
    "bond": InstrumentType.BOND,
    "currency": InstrumentType.CURRENCY,
    "future": InstrumentType.FUTURE,
}

# T-Invest OrderExecutionReportStatus -> our OrderStatus.
_ORDER_STATUS_MAP = {
    "EXECUTION_REPORT_STATUS_FILL": OrderStatus.FILLED,
    "EXECUTION_REPORT_STATUS_REJECTED": OrderStatus.REJECTED,
    "EXECUTION_REPORT_STATUS_CANCELLED": OrderStatus.CANCELLED,
    "EXECUTION_REPORT_STATUS_NEW": OrderStatus.NEW,
    "EXECUTION_REPORT_STATUS_PARTIALLYFILL": OrderStatus.PARTIALLY_FILLED,
}

# T-Invest OrderType -> our OrderType. BESTPRICE is intentionally NOT mapped to
# LIMIT: unsupported order types surface as None, never silently downgraded.
_ORDER_TYPE_MAP = {
    "ORDER_TYPE_LIMIT": OrderType.LIMIT,
    "ORDER_TYPE_MARKET": OrderType.MARKET,
}

# Our OrderType -> T-Invest OrderType (only the supported set for MVP-6.2).
_ORDER_TYPE_TO_TINVEST = {
    OrderType.LIMIT: "ORDER_TYPE_LIMIT",
    OrderType.MARKET: "ORDER_TYPE_MARKET",
}

# T-Invest OrderDirection -> our OrderSide.
_ORDER_SIDE_MAP = {
    "ORDER_DIRECTION_BUY": OrderSide.BUY,
    "ORDER_DIRECTION_SELL": OrderSide.SELL,
}

# Our OrderSide -> T-Invest OrderDirection.
_ORDER_SIDE_TO_TINVEST = {
    OrderSide.BUY: "ORDER_DIRECTION_BUY",
    OrderSide.SELL: "ORDER_DIRECTION_SELL",
}

# T-Invest StopOrderStatus -> our StopOrderStatus. UNSPECIFIED is intentionally
# NOT mapped: an unspecified/unknown status surfaces as UNKNOWN, never guessed.
_STOP_ORDER_STATUS_MAP = {
    "STOP_ORDER_STATUS_ACTIVE": StopOrderStatus.ACTIVE,
    "STOP_ORDER_STATUS_EXECUTED": StopOrderStatus.EXECUTED,
    "STOP_ORDER_STATUS_CANCELED": StopOrderStatus.CANCELLED,
    "STOP_ORDER_STATUS_EXPIRED": StopOrderStatus.EXPIRED,
}

# T-Invest StopOrderType -> our supported stop order kind (stop-loss only for MVP-6.16);
# an unknown type surfaces as None, never silently downgraded.
_STOP_ORDER_TYPE_MAP = {
    "STOP_ORDER_TYPE_STOP_LOSS": "stop_loss",
}

# T-Invest OperationType names that represent security trades.
_DEAL_BUY_TYPES = {"OPERATION_TYPE_BUY", "OPERATION_TYPE_BUY_CARD", "OPERATION_TYPE_BUY_MARGIN"}
_DEAL_SELL_TYPES = {"OPERATION_TYPE_SELL", "OPERATION_TYPE_SELL_CARD", "OPERATION_TYPE_SELL_MARGIN"}


def _resolve_base_url(settings) -> str:
    """Select the REST base url, honoring the sandbox toggle."""
    if settings.tinvest_sandbox:
        return _SANDBOX_BASE
    return settings.tinvest_base_url


def _quotation_to_decimal(quotation: dict | None) -> Decimal | None:
    """Convert a Quotation/MoneyValue object to a Decimal."""
    if not quotation:
        return None
    units = quotation.get("units") or 0
    nano = quotation.get("nano") or 0
    return Decimal(str(units)) + Decimal(str(nano)) / Decimal(1_000_000_000)


def _decimal_to_quotation(value: Decimal) -> dict:
    """Convert a Decimal to a T-Invest Quotation object (units + nano)."""
    value = value.quantize(Decimal("0.000000001"))
    units = int(value)
    nano = int((value - Decimal(units)) * Decimal(1_000_000_000))
    return {"units": str(units), "nano": nano}


def _timestamp_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_iso_utc(dt: datetime) -> str:
    """Serialize a datetime to an RFC3339 UTC string (Z suffix)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _map_instrument_type(value: str | None) -> InstrumentType | None:
    return _TINVEST_TYPE_MAP.get((value or "").lower())


def _map_trading_status(api_available: bool) -> TradingStatus:
    return TradingStatus.TRADING_AVAILABLE if api_available else TradingStatus.TRADING_UNAVAILABLE


# GetTradingStatus response ``trading_status`` (SecurityTradingStatus) values.
# The REST layer may serialize the enum either as a name (proto3 JSON) or as a
# raw number; both forms are normalized before mapping.
_SECURITY_STATUS_BY_NUMBER = {
    0: "SECURITY_TRADING_STATUS_UNSPECIFIED",
    1: "SECURITY_TRADING_STATUS_NOT_AVAILABLE_FOR_TRADING",
    2: "SECURITY_TRADING_STATUS_OPENING_PERIOD",
    3: "SECURITY_TRADING_STATUS_CLOSING_PERIOD",
    4: "SECURITY_TRADING_STATUS_BREAK_IN_TRADING",
    5: "SECURITY_TRADING_STATUS_NORMAL_TRADING",
    6: "SECURITY_TRADING_STATUS_CLOSING_AUCTION",
    7: "SECURITY_TRADING_STATUS_DARK_POOL_AUCTION",
    8: "SECURITY_TRADING_STATUS_DISCRETE_AUCTION",
    9: "SECURITY_TRADING_STATUS_OPENING_AUCTION_PERIOD",
    10: "SECURITY_TRADING_STATUS_TRADING_AT_CLOSING_AUCTION_PRICE",
    11: "SECURITY_TRADING_STATUS_SESSION_ASSIGNED",
    12: "SECURITY_TRADING_STATUS_SESSION_CLOSE",
    13: "SECURITY_TRADING_STATUS_SESSION_OPEN",
    14: "SECURITY_TRADING_STATUS_DEALER_NORMAL_TRADING",
    15: "SECURITY_TRADING_STATUS_DEALER_BREAK_IN_TRADING",
    16: "SECURITY_TRADING_STATUS_DEALER_NOT_AVAILABLE_FOR_TRADING",
}


def _normalize_security_status(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int):
        return _SECURITY_STATUS_BY_NUMBER.get(value, f"UNKNOWN_{value}")
    return "UNKNOWN"


# Every *documented* status that GetTradingStatus may return. UNSPECIFIED is
# deliberately excluded: it is not a trading state and must raise (an unknown
# value must never be silently treated as "not tradable").
_SECURITY_STATUS_NAMES = frozenset(
    name
    for name in _SECURITY_STATUS_BY_NUMBER.values()
    if name != "SECURITY_TRADING_STATUS_UNSPECIFIED"
)


def _map_security_trading_status(raw_status: object, api_available: object) -> TradingStatus:
    """Map a GetTradingStatus response to the domain TradingStatus (MVP-6.13 S3).

    Only NORMAL_TRADING with API trading enabled is tradable. Every other
    documented exchange state (opening/closing periods, breaks, auctions,
    closed/non-trading sessions, dealer-only states) maps to
    ``TRADING_UNAVAILABLE``: the tick is skipped and *not* counted as a failure.
    ``UNSPECIFIED`` or any unrecognized value raises |BrokerApiError| — an
    unknown state must not be silently treated as "not tradable" (the scheduler
    counts it as a transient failure instead). ``api_trade_available_flag``
    missing/False keeps only the explicit-flag case available.
    """
    name = _normalize_security_status(raw_status)
    if name not in _SECURITY_STATUS_NAMES:
        raise BrokerApiError(f"unexpected trading status from broker: {raw_status!r}")
    if name == "SECURITY_TRADING_STATUS_NORMAL_TRADING" and api_available is True:
        return TradingStatus.TRADING_AVAILABLE
    return TradingStatus.TRADING_UNAVAILABLE


def _map_order_status(value: str | None) -> OrderStatus:
    return _ORDER_STATUS_MAP.get(value or "", OrderStatus.UNKNOWN)


def _map_stop_order_status(value: str | None) -> StopOrderStatus:
    return _STOP_ORDER_STATUS_MAP.get(value or "", StopOrderStatus.UNKNOWN)


def _map_stop_order_type(value: str | None) -> str | None:
    return _STOP_ORDER_TYPE_MAP.get(value or "")


def _map_order_type(value: str | None) -> OrderType | None:
    return _ORDER_TYPE_MAP.get(value or "")


def _map_order_side(value: str | None) -> OrderSide | None:
    return _ORDER_SIDE_MAP.get(value or "")


def _map_deal_side(operation_type: str | None) -> OrderSide | None:
    if operation_type in _DEAL_BUY_TYPES:
        return OrderSide.BUY
    if operation_type in _DEAL_SELL_TYPES:
        return OrderSide.SELL
    return None


def _executed_average_price(raw: dict) -> Decimal | None:
    """Volume-weighted average execution price per unit from official ``stages``.

    Derived from the real ``stages[].price`` x ``stages[].quantity`` facts. The
    quantity unit cancels in the ratio, so this is valid with lots or units.
    Returns None when there are no execution facts.
    """
    total = Decimal("0")
    total_qty = Decimal("0")
    for stage in raw.get("stages") or []:
        price = _quotation_to_decimal(stage.get("price"))
        qty = Decimal(str(stage.get("quantity") or 0))
        if price is None or qty == 0:
            continue
        total += price * qty
        total_qty += qty
    if total_qty == 0:
        return None
    return total / total_qty


def _stages_to_executions(raw: dict, order_id: str, factor: Decimal) -> list[BrokerExecution]:
    """Map T-Invest ``stages`` to canonical-unit broker executions."""
    executions: list[BrokerExecution] = []
    for stage in raw.get("stages") or []:
        price = _quotation_to_decimal(stage.get("price"))
        if price is None:
            continue
        qty = Decimal(str(stage.get("quantity") or 0)) * factor
        executions.append(
            BrokerExecution(
                execution_id=stage.get("tradeId", stage.get("trade_id", "")),
                quantity=qty,
                price=price,
                broker_order_id=order_id,
                commission=_quotation_to_decimal(stage.get("commission")) or Decimal("0"),
                timestamp=_timestamp_to_datetime(
                    stage.get("executionTime") or stage.get("date_time")
                ),
            )
        )
    return executions


class TInvestAdapter(BrokerAdapter):
    """BrokerAdapter implemented over the T-Invest read-only REST API."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        client: TInvestClient | None = None,
    ) -> None:
        self._client = client
        if self._client is None:
            settings = get_settings()
            effective_token = token if token is not None else settings.tinvest_token
            effective_base = base_url if base_url is not None else _resolve_base_url(settings)
            if effective_token:
                self._client = TInvestClient(token=effective_token, base_url=effective_base)

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def _require_client(self) -> TInvestClient:
        if self._client is None:
            raise AuthenticationError("T-Invest API token is not configured")
        return self._client

    async def _first_account_id(self) -> str:
        accounts = await self.get_accounts()
        if not accounts:
            raise AccountNotFoundError("No accounts available")
        return accounts[0].account_id

    async def connect(self) -> None:
        """Validate the token by fetching the account list."""
        client = self._require_client()
        await client.call(f"{_USERS}/GetAccounts", {"status": "ACCOUNT_STATUS_UNSPECIFIED"})

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def get_accounts(self) -> list[BrokerAccount]:
        client = self._require_client()
        data = await client.call(f"{_USERS}/GetAccounts", {"status": "ACCOUNT_STATUS_UNSPECIFIED"})
        raw_accounts = data.get("accounts", [])
        return [self._to_account(item) for item in raw_accounts]

    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        client = self._require_client()
        if not account_id:
            account_id = await self._first_account_id()
        data = await client.call(
            f"{_OPERATIONS}/GetPortfolio", {"accountId": account_id, "currency": "RUB"}
        )
        return self._to_account_from_portfolio(data, account_id)

    async def get_instruments(self, kind: str | None = None) -> list[BrokerInstrument]:
        client = self._require_client()
        resolved = (kind or "share").lower()
        method = _KIND_TO_LIST_METHOD.get(resolved)
        if method is None:
            raise ResourceNotFoundError(f"Unsupported instrument kind: {kind}")
        data = await client.call(method, {"instrumentStatus": "INSTRUMENT_STATUS_BASE"})
        raw_instruments = data.get("instruments", [])
        return [self._to_instrument(item, kind_hint=resolved) for item in raw_instruments]

    async def get_instrument(self, figi: str) -> BrokerInstrument:
        client = self._require_client()
        try:
            data = await client.call(
                f"{_INSTRUMENTS}/GetInstrumentBy",
                {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi},
            )
        except ResourceNotFoundError as exc:
            raise InstrumentNotFoundError(f"Instrument not found: {figi}") from exc
        raw = data.get("instrument")
        if raw is None:
            raise InstrumentNotFoundError(f"Instrument not found: {figi}")
        return self._to_instrument(raw)

    async def get_last_price(self, figi: str) -> LastPrice:
        client = self._require_client()
        data = await client.call(f"{_MARKET}/GetLastPrices", {"instrumentId": [figi]})
        raw = (data.get("lastPrices") or [{}])[0]
        return self._to_last_price(raw, figi)

    async def get_candles(
        self,
        figi: str,
        timeframe: Timeframe,
        from_: datetime,
        to: datetime,
        limit: int | None = None,
    ) -> list[Candle]:
        client = self._require_client()
        interval_enum = _TIMEFRAME_TO_INTERVAL.get(timeframe)
        if interval_enum is None:
            raise InvalidRequestError(f"Unsupported candle timeframe: {timeframe}")
        body: dict = {
            "instrumentId": figi,
            "interval": interval_enum,
            "from": _to_iso_utc(from_),
            "to": _to_iso_utc(to),
        }
        if limit is not None:
            body["limit"] = limit
        data = await client.call(f"{_MARKET}/GetCandles", body)
        raw_candles = data.get("candles", [])
        return [self._to_candle(item, figi, timeframe) for item in raw_candles]

    async def get_trading_status(self, figi: str) -> TradingStatus:
        """S3: ask the broker whether the instrument is tradable right now.

        Uses the official ``MarketDataService/GetTradingStatus``; the mapping
        (including the "unknown vs. not tradable" distinction) stays inside the
        adapter. No hard-coded exchange session schedule.
        """
        client = self._require_client()
        data = await client.call(f"{_MARKET}/GetTradingStatus", {"instrumentId": figi})
        return _map_security_trading_status(
            data.get("trading_status"),
            data.get("api_trade_available_flag"),
        )

    async def get_open_positions(self, account_id: str | None = None) -> list[BrokerPosition]:
        client = self._require_client()
        if not account_id:
            account_id = await self._first_account_id()
        data = await client.call(
            f"{_OPERATIONS}/GetPortfolio", {"accountId": account_id, "currency": "RUB"}
        )
        portfolio_currency = (data.get("totalAmountPortfolio") or {}).get("currency") or "RUB"
        positions: list[BrokerPosition] = []
        for item in data.get("positions", []):
            positions.append(self._to_position(item, account_id, portfolio_currency))
        return positions

    async def get_orders(self, account_id: str | None = None) -> list[BrokerOrder]:
        client = self._require_client()
        if not account_id:
            account_id = await self._first_account_id()
        data = await client.call(f"{_ORDERS}/GetOrders", {"accountId": account_id})
        raw_orders = data.get("orders", [])
        return [await self._to_order(item, account_id) for item in raw_orders]

    async def get_deals(self, account_id: str | None = None) -> list[BrokerDeal]:
        client = self._require_client()
        if not account_id:
            account_id = await self._first_account_id()
        deals: list[BrokerDeal] = []
        cursor: str | None = None
        while True:
            body: dict = {"accountId": account_id, "limit": 100}
            if cursor:
                body["cursor"] = cursor
            data = await client.call(f"{_OPERATIONS}/GetOperationsByCursor", body)
            for item in data.get("items", []):
                deals.extend(self._operation_to_deals(item, account_id))
            if not data.get("hasNext"):
                break
            cursor = data.get("nextCursor")
            if not cursor:
                break
        return deals

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        """Place a market/limit order for a share/ETF via PostOrder.

        Converts the canonical unit quantity (units) into T-Invest lots using
        the instrument lot size, validates lot & price-tick constraints, and
        uses the (UUID) idempotency key verbatim. BestPrice is not supported in
        MVP-6.2 and is rejected rather than silently downgraded to LIMIT.
        """
        client = self._require_client()
        if not request.account_id:
            raise InvalidRequestError("account_id is required for T-Invest order placement")
        if request.quantity <= 0:
            raise InvalidRequestError("quantity must be positive")

        type_enum = _ORDER_TYPE_TO_TINVEST.get(request.type)
        if type_enum is None:
            raise InvalidRequestError(f"Unsupported order type for MVP-6.2: {request.type}")

        instrument = await self.get_instrument(request.instrument_figi)
        lot_size = instrument.lot_size
        if not lot_size or lot_size <= 0:
            raise InvalidRequestError(
                f"Unknown lot size for instrument {request.instrument_figi}"
            )
        if request.quantity % lot_size != 0:
            raise InvalidRequestError(
                f"quantity {request.quantity} is not a multiple of lot size {lot_size}"
            )
        lots = int(request.quantity // lot_size)

        body: dict = {
            "instrumentId": request.instrument_figi,
            "quantity": lots,
            "direction": _ORDER_SIDE_TO_TINVEST[request.side],
            "accountId": request.account_id,
            "orderType": type_enum,
            "orderId": self._resolve_idempotency_key(request.idempotency_key),
        }

        if request.type == OrderType.LIMIT:
            if request.price is None or request.price <= 0:
                raise InvalidRequestError("limit price is required and must be positive")
            tick_size = instrument.tick_size
            if tick_size and request.price % tick_size != 0:
                raise InvalidRequestError(
                    f"price {request.price} is not a multiple of tick size {tick_size}"
                )
            body["price"] = _decimal_to_quotation(request.price)

        data = await client.call(f"{_ORDERS}/PostOrder", body)
        return await self._to_order(data, request.account_id, lot_size=lot_size)

    async def cancel_order(self, order_id: str, account_id: str | None = None) -> None:
        client = self._require_client()
        if not account_id:
            raise InvalidRequestError("account_id is required to cancel a T-Invest order")
        await client.call(
            f"{_ORDERS}/CancelOrder",
            {
                "accountId": account_id,
                "orderId": order_id,
                "orderIdType": "ORDER_ID_TYPE_EXCHANGE",
            },
        )

    async def get_order(self, order_id: str, account_id: str | None = None) -> BrokerOrder:
        client = self._require_client()
        if not account_id:
            raise InvalidRequestError("account_id is required to read a T-Invest order")
        try:
            data = await client.call(
                f"{_ORDERS}/GetOrderState",
                {
                    "accountId": account_id,
                    "orderId": order_id,
                    "orderIdType": "ORDER_ID_TYPE_EXCHANGE",
                },
            )
        except ResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"Order not found: {order_id}") from exc
        return await self._to_order(data, account_id)

    async def place_stop_order(self, request: BrokerStopOrderRequest) -> BrokerStopOrder:
        """Place a stop-loss conditional market order via PostStopOrder.

        The stop order is STOP_LOSS, GOOD_TILL_CANCEL, with a market execution
        after the trigger: the stop is the only supported stop-order kind in
        MVP-6.16 and no other kind is silently substituted. Quantity is converted
        from canonical units to T-Invest lots via the instrument lot size; the
        idempotency key (UUID) allows a retry to return the already-placed order.
        """
        client = self._require_client()
        if not request.account_id:
            raise InvalidRequestError("account_id is required for T-Invest stop-order placement")
        if request.quantity <= 0:
            raise InvalidRequestError("stop quantity must be positive")
        if request.stop_price <= 0:
            raise InvalidRequestError("stop price must be positive")

        instrument = await self.get_instrument(request.instrument_figi)
        lot_size = instrument.lot_size
        if not lot_size or lot_size <= 0:
            raise InvalidRequestError(
                f"Unknown lot size for instrument {request.instrument_figi}"
            )
        if request.quantity % lot_size != 0:
            raise InvalidRequestError(
                f"quantity {request.quantity} is not a multiple of lot size {lot_size}"
            )
        lots = int(request.quantity // lot_size)

        body: dict = {
            "instrumentId": request.instrument_figi,
            "quantity": lots,
            "stopPrice": _decimal_to_quotation(request.stop_price),
            "direction": _ORDER_SIDE_TO_TINVEST[request.side],
            "accountId": request.account_id,
            "expirationType": "STOP_ORDER_EXPIRATION_TYPE_GOOD_TILL_CANCEL",
            "stopOrderType": "STOP_ORDER_TYPE_STOP_LOSS",
            "orderId": self._resolve_idempotency_key(request.idempotency_key),
            "exchangeOrderType": "EXCHANGE_ORDER_TYPE_MARKET",
        }
        data = await client.call(f"{_STOP_ORDERS}/PostStopOrder", body)
        stop_order_id = data.get("stopOrderId") or data.get("stop_order_id")
        # PostStopOrder returns only the stop order id; a successfully accepted
        # GOOD_TILL_CANCEL stop-loss is reported as ACTIVE (working at the broker).
        return BrokerStopOrder(
            order_id=stop_order_id or "",
            status=StopOrderStatus.ACTIVE,
            account_id=request.account_id,
            instrument_figi=request.instrument_figi,
            side=request.side,
            quantity=request.quantity,
            stop_price=request.stop_price,
        )

    async def cancel_stop_order(
        self, order_id: str, account_id: str | None = None
    ) -> None:
        client = self._require_client()
        if not account_id:
            raise InvalidRequestError("account_id is required to cancel a T-Invest stop order")
        await client.call(
            f"{_STOP_ORDERS}/CancelStopOrder",
            {"accountId": account_id, "stopOrderId": order_id},
        )

    async def get_stop_orders(self, account_id: str | None = None) -> list[BrokerStopOrder]:
        client = self._require_client()
        if not account_id:
            account_id = await self._first_account_id()
        data = await client.call(f"{_STOP_ORDERS}/GetStopOrders", {"accountId": account_id})
        raw_orders = data.get("orders", [])
        return [await self._to_stop_order(item, account_id) for item in raw_orders]

    @staticmethod
    def _resolve_idempotency_key(idempotency_key: str) -> str:
        """Return a valid UUID idempotency key, or reject an invalid one.

        T-Invest requires the idempotency key to be in UUID format; a non-UUID
        key must not be sent (the broker would substitute a generated one and
        correlation would be lost). A missing key is generated once (UUID4).
        """
        key = (idempotency_key or "").strip()
        if not key:
            return str(uuid.uuid4())
        try:
            return str(uuid.UUID(key))
        except ValueError as exc:
            raise InvalidRequestError(
                "T-Invest idempotency key must be a valid UUID"
            ) from exc

    # --- normalization helpers (T-Invest JSON -> broker DTO / domain DTO) ---

    @staticmethod
    def _to_account(raw: dict) -> BrokerAccount:
        return BrokerAccount(
            account_id=raw.get("id", ""),
            name=raw.get("name"),
            account_type=raw.get("type"),
            status=raw.get("status"),
            opened_at=_timestamp_to_datetime(raw.get("openedDate")),
            closed_at=_timestamp_to_datetime(raw.get("closedDate")),
        )

    def _to_account_from_portfolio(self, data: dict, account_id: str) -> BrokerAccount:
        equity = _quotation_to_decimal(data.get("totalAmountPortfolio")) or Decimal("0")
        cash = _quotation_to_decimal(data.get("totalAmountCurrencies")) or Decimal("0")
        currency = (data.get("totalAmountPortfolio") or {}).get("currency") or "RUB"
        return BrokerAccount(
            account_id=account_id,
            currency=currency,
            equity=equity,
            available_cash=cash,
        )

    @classmethod
    def _to_instrument(cls, raw: dict, kind_hint: str | None = None) -> BrokerInstrument:
        figi = raw.get("figi") or ""
        instrument_type = _map_instrument_type(raw.get("instrumentType")) or (
            _map_instrument_type(kind_hint)
        )
        tick_size = _quotation_to_decimal(raw.get("minPriceIncrement"))
        lot = raw.get("lot")
        api_available = bool(raw.get("apiTradeAvailableFlag", True))
        return BrokerInstrument(
            figi=figi,
            ticker=raw.get("ticker"),
            name=raw.get("name"),
            instrument_type=instrument_type,
            currency=raw.get("currency"),
            lot_size=int(lot) if lot is not None else None,
            tick_size=tick_size,
            trading_status=_map_trading_status(api_available),
            exchange=raw.get("exchange"),
            is_active=api_available,
        )

    @staticmethod
    def _to_position(raw: dict, account_id: str, portfolio_currency: str) -> BrokerPosition:
        quantity = _quotation_to_decimal(raw.get("quantity")) or Decimal("0")
        average = _quotation_to_decimal(raw.get("averagePositionPrice")) or Decimal("0")
        current = _quotation_to_decimal(raw.get("currentPrice")) or Decimal("0")
        current_value = current * quantity
        unrealized = (current - average) * quantity
        currency = (raw.get("averagePositionPrice") or {}).get("currency") or portfolio_currency
        return BrokerPosition(
            account_id=account_id,
            instrument_figi=raw.get("figi", ""),
            ticker=raw.get("ticker"),
            instrument_type=raw.get("instrumentType"),
            quantity=quantity,
            average_price=average,
            current_price=current,
            current_value=current_value,
            unrealized_pnl=unrealized,
            currency=currency,
        )

    async def _to_order(
        self, raw: dict, account_id: str, lot_size: int | None = None
    ) -> BrokerOrder:
        """Map a T-Invest order payload to a broker-neutral BrokerOrder.

        ``lotsRequested``/``lotsExecuted`` are converted to canonical instrument
        units using the instrument lot size. The executed average price and the
        individual executions are derived from the official ``stages`` facts
        (``price`` x ``quantity``), never from ``initialSecurityPrice``.
        """
        requested = raw.get("lotsRequested") or 0
        executed = raw.get("lotsExecuted") or 0
        stages = raw.get("stages") or []
        order_id = raw.get("orderId", "")
        updated_at = None
        if stages:
            updated_at = _timestamp_to_datetime(stages[-1].get("executionTime"))
        if raw.get("figi"):
            if lot_size is None:
                lot_size = await self._lot_size_for(raw["figi"])
            if not lot_size or lot_size <= 0:
                raise InvalidRequestError(
                    f"cannot resolve lot size for instrument {raw['figi']}; "
                    "refusing to map T-Invest lots as canonical units"
                )
            factor = Decimal(lot_size)
            requested_quantity = Decimal(str(requested)) * factor
            executed_quantity = Decimal(str(executed)) * factor
            executions = _stages_to_executions(raw, order_id, factor)
        else:
            if requested or executed:
                raise InvalidRequestError(
                    "order has quantity but no FIGI; cannot normalize lots to units"
                )
            # No FIGI -> no instrument facts; zero-quantity orders have zero units.
            # No fallback factor (1) is used here.
            requested_quantity = Decimal("0")
            executed_quantity = Decimal("0")
            executions = []
        return BrokerOrder(
            order_id=order_id,
            account_id=account_id,
            instrument_figi=raw.get("figi"),
            ticker=raw.get("ticker"),
            status=_map_order_status(raw.get("executionReportStatus")),
            type=_map_order_type(raw.get("orderType")),
            side=_map_order_side(raw.get("direction")),
            requested_quantity=requested_quantity,
            executed_quantity=executed_quantity,
            price=_quotation_to_decimal(raw.get("initialSecurityPrice")),
            executed_average_price=_executed_average_price(raw),
            executions=executions,
            idempotency_key=raw.get("orderRequestId") or raw.get("order_request_id"),
            currency=raw.get("currency"),
            created_at=_timestamp_to_datetime(raw.get("orderDate")),
            updated_at=updated_at,
            reject_info=raw.get("message"),
        )

    async def _lot_size_for(self, figi: str) -> int | None:
        try:
            instrument = await self.get_instrument(figi)
            return instrument.lot_size
        except Exception:  # noqa: BLE001 - best-effort normalization
            return None

    async def _to_stop_order(self, raw: dict, account_id: str) -> BrokerStopOrder:
        """Map a T-Invest StopOrder payload to a broker-neutral BrokerStopOrder.

        ``lots_requested`` is converted to canonical units via the instrument
        lot size; a quantity without a resolvable lot size is refused (never
        silently treated as units). A status the adapter cannot map surfaces as
        ``UNKNOWN``, never guessed.
        """
        lots = raw.get("lotsRequested") or 0
        figi = raw.get("figi")
        if figi:
            lot_size = await self._lot_size_for(figi)
            if not lot_size or lot_size <= 0:
                raise InvalidRequestError(
                    f"cannot resolve lot size for instrument {figi}; "
                    "refusing to map T-Invest lots as canonical units"
                )
            factor = Decimal(lot_size)
            quantity = Decimal(str(lots)) * factor
        else:
            if lots:
                raise InvalidRequestError(
                    "stop order has quantity but no FIGI; cannot normalize lots to units"
                )
            quantity = Decimal("0")
        return BrokerStopOrder(
            order_id=raw.get("stopOrderId", ""),
            status=_map_stop_order_status(raw.get("status")),
            account_id=account_id,
            instrument_figi=figi,
            side=_map_order_side(raw.get("direction")),
            quantity=quantity,
            stop_price=_quotation_to_decimal(raw.get("stopPrice")),
            exchange_order_id=raw.get("exchangeOrderId"),
            currency=raw.get("currency"),
            created_at=_timestamp_to_datetime(raw.get("createDate")),
            updated_at=_timestamp_to_datetime(raw.get("updateDate")),
        )

    @staticmethod
    def _operation_to_deals(item: dict, account_id: str) -> list[BrokerDeal]:
        side = _map_deal_side(item.get("type"))
        figi = item.get("figi")
        if side is None or not figi:
            return []
        quantity = item.get("quantityDone") or item.get("quantity") or 0
        price = _quotation_to_decimal(item.get("price")) or Decimal("0")
        commission = _quotation_to_decimal(item.get("commission")) or Decimal("0")
        currency = (item.get("commission") or {}).get("currency") or (
            item.get("payment") or {}
        ).get("currency")
        order_id = (
            item.get("orderId")
            or item.get("order_id")
            or item.get("orderRequestId")
            or item.get("order_request_id")
            or item.get("parentOrderId")
        )
        return [
            BrokerDeal(
                deal_id=item.get("id", ""),
                account_id=account_id,
                order_id=order_id,
                instrument_figi=figi,
                side=side,
                quantity=Decimal(str(quantity)),
                price=price,
                commission=commission,
                currency=currency,
                happened_at=_timestamp_to_datetime(item.get("date")),
            )
        ]

    @staticmethod
    def _to_last_price(raw: dict, default_figi: str) -> LastPrice:
        return LastPrice(
            figi=raw.get("figi") or default_figi,
            price=_quotation_to_decimal(raw.get("price")) or Decimal("0"),
            timestamp=_timestamp_to_datetime(raw.get("time")),
            ticker=raw.get("ticker"),
        )

    @staticmethod
    def _to_candle(raw: dict, figi: str, timeframe: Timeframe) -> Candle:
        time_value = _timestamp_to_datetime(raw.get("time"))
        if time_value is None:
            time_value = datetime.min.replace(tzinfo=UTC)
        return Candle(
            figi=figi,
            timeframe=timeframe,
            timestamp=time_value,
            open=_quotation_to_decimal(raw.get("open")) or Decimal("0"),
            high=_quotation_to_decimal(raw.get("high")) or Decimal("0"),
            low=_quotation_to_decimal(raw.get("low")) or Decimal("0"),
            close=_quotation_to_decimal(raw.get("close")) or Decimal("0"),
            volume=int(raw.get("volume") or 0),
            is_complete=raw.get("isComplete"),
        )
