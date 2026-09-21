"""TInvestAdapter — read-only integration with T-Invest API.

Implements the broker-agnostic |BrokerAdapter| interface and hides all T-Invest
specifics: instrument types, trading statuses, candle intervals, order statuses,
directions and deal types are mapped to our internal enums here, and only domain
DTOs leave the adapter. No trade placement — trading methods deliberately raise
NotImplementedError.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from app.brokers.base import (
    BrokerAccount,
    BrokerAdapter,
    BrokerDeal,
    BrokerInstrument,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)
from app.brokers.tinvest_client import TInvestClient
from app.brokers.tinvest_errors import (
    AccountNotFoundError,
    AuthenticationError,
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
_INSTRUMENTS = "tinkoff.public.invest.api.contract.v1.InstrumentsService"
_MARKET = "tinkoff.public.invest.api.contract.v1.MarketDataService"

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

# T-Invest OrderType -> our OrderType.
_ORDER_TYPE_MAP = {
    "ORDER_TYPE_LIMIT": OrderType.LIMIT,
    "ORDER_TYPE_MARKET": OrderType.MARKET,
    "ORDER_TYPE_BESTPRICE": OrderType.LIMIT,
}

# T-Invest OrderDirection -> our OrderSide.
_ORDER_SIDE_MAP = {
    "ORDER_DIRECTION_BUY": OrderSide.BUY,
    "ORDER_DIRECTION_SELL": OrderSide.SELL,
}

# T-Invest OperationType names that represent security trades.
_DEAL_BUY_TYPES = {"OPERATION_TYPE_BUY", "OPERATION_TYPE_BUY_CARD", "OPERATION_TYPE_BUY_MARGIN"}
_DEAL_SELL_TYPES = {"OPERATION_TYPE_SELL", "OPERATION_TYPE_SELL_CARD", "OPERATION_TYPE_SELL_MARGIN"}

_NOT_IMPLEMENTED = "Trade execution is not implemented in the read-only integration"


def _quotation_to_decimal(quotation: dict | None) -> Decimal | None:
    """Convert a Quotation/MoneyValue object to a Decimal."""
    if not quotation:
        return None
    units = quotation.get("units") or 0
    nano = quotation.get("nano") or 0
    return Decimal(str(units)) + Decimal(str(nano)) / Decimal(1_000_000_000)


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


def _map_order_status(value: str | None) -> OrderStatus:
    return _ORDER_STATUS_MAP.get(value or "", OrderStatus.ERROR)


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
            effective_base = base_url if base_url is not None else settings.tinvest_base_url
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
        return [self._to_order(item, account_id) for item in raw_orders]

    async def get_order(self, order_id: str) -> BrokerOrder:
        client = self._require_client()
        account_id = await self._first_account_id()
        data = await client.call(
            f"{_ORDERS}/GetOrderState", {"accountId": account_id, "orderId": order_id}
        )
        return self._to_order(data, account_id)

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
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

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

    @staticmethod
    def _to_order(raw: dict, account_id: str) -> BrokerOrder:
        requested = raw.get("lotsRequested") or 0
        executed = raw.get("lotsExecuted") or 0
        updated_at = None
        stages = raw.get("stages") or []
        if stages:
            updated_at = _timestamp_to_datetime(stages[-1].get("executionTime"))
        return BrokerOrder(
            order_id=raw.get("orderId", ""),
            account_id=account_id,
            instrument_figi=raw.get("figi"),
            ticker=raw.get("ticker"),
            status=_map_order_status(raw.get("executionReportStatus")),
            type=_map_order_type(raw.get("orderType")),
            side=_map_order_side(raw.get("direction")),
            requested_quantity=Decimal(str(requested)),
            executed_quantity=Decimal(str(executed)),
            price=_quotation_to_decimal(raw.get("initialSecurityPrice")),
            currency=raw.get("currency"),
            created_at=_timestamp_to_datetime(raw.get("orderDate")),
            updated_at=updated_at,
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
        return [
            BrokerDeal(
                deal_id=item.get("id", ""),
                account_id=account_id,
                order_id=None,
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
