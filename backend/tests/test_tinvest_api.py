"""REST API tests for the read-only endpoints (no real token/network)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_account_service, get_broker_adapter, get_instrument_service
from app.brokers import (
    AuthenticationError,
    TInvestAdapter,
)
from app.main import app
from app.models.instrument import Instrument
from tests.fakes import FakeInstrumentService, TInvestFakeClient

_GET_ACCOUNTS = "tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"
_GET_INSTRUMENT = "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy"
_CANDLES = "tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"


def _override_broker(adapter: TInvestAdapter) -> None:
    app.dependency_overrides[get_broker_adapter] = lambda: adapter


def _override_instruments(service: FakeInstrumentService) -> None:
    app.dependency_overrides[get_instrument_service] = lambda: service


def _override_account_local_ids(local: dict[str, int] | None = None) -> None:
    """Stub AccountService: no DB session, fixed external->local mapping."""
    mapping = local or {}

    class _FakeAccountService:
        async def local_by_broker_ids(self, external_account_ids, broker: str = "tinvest"):
            return mapping

    app.dependency_overrides[get_account_service] = lambda: _FakeAccountService()


def _clear() -> None:
    app.dependency_overrides.pop(get_broker_adapter, None)
    app.dependency_overrides.pop(get_instrument_service, None)
    app.dependency_overrides.pop(get_account_service, None)


def test_status_not_configured() -> None:
    _override_broker(TInvestAdapter())
    try:
        with TestClient(app) as client:
            response = client.get("/api/tinvest/status")
        assert response.status_code == 200
        assert response.json()["status"] == "not_configured"
    finally:
        _clear()


def test_status_connected() -> None:
    fake = TInvestFakeClient(responses={_GET_ACCOUNTS: {"accounts": []}})
    _override_broker(TInvestAdapter(client=fake))
    try:
        with TestClient(app) as client:
            response = client.get("/api/tinvest/status")
        assert response.status_code == 200
        assert response.json()["status"] == "connected"
    finally:
        _clear()


def test_list_accounts() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {
                "accounts": [
                    {
                        "id": "acc-1",
                        "type": "ACCOUNT_TYPE_TINKOFF",
                        "name": "Main",
                        "status": "ACCOUNT_STATUS_OPEN",
                    }
                ]
            }
        }
    )
    _override_broker(TInvestAdapter(client=fake))
    _override_account_local_ids()
    try:
        with TestClient(app) as client:
            response = client.get("/api/accounts")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["account_id"] == "acc-1"
        assert body[0]["status"] == "ACCOUNT_STATUS_OPEN"
        # R2: untracked broker accounts expose local id/is_saved flag.
        assert body[0]["id"] is None
        assert body[0]["is_saved"] is False
    finally:
        _clear()


def test_list_instruments_via_service() -> None:
    instrument = Instrument(
        figi="BBG004730N88", ticker="SBER", name="Sberbank", instrument_type="SHARE", currency="RUB"
    )
    _override_instruments(FakeInstrumentService([instrument]))
    try:
        with TestClient(app) as client:
            response = client.get("/api/instruments")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["figi"] == "BBG004730N88"
        assert body[0]["instrument_type"] == "SHARE"
    finally:
        _clear()


def test_list_instruments_includes_first_candle_dates() -> None:
    # MVP-7.6 (H3): GET /api/instruments exposes the broker's earliest history
    # dates (UTC, ISO); missing broker facts stay null in the response.
    from datetime import UTC, datetime

    instrument = Instrument(
        figi="BBG004730N88",
        ticker="SBER",
        name="Sberbank",
        instrument_type="SHARE",
        currency="RUB",
        first_1min_candle_date=datetime(2020, 2, 7, tzinfo=UTC),
        first_1day_candle_date=datetime(1998, 1, 1, tzinfo=UTC),
    )
    bare = Instrument(figi="F2", ticker="GAZP", instrument_type="SHARE", currency="RUB")
    _override_instruments(FakeInstrumentService([instrument, bare]))
    try:
        with TestClient(app) as client:
            response = client.get("/api/instruments")
        assert response.status_code == 200
        body = response.json()

        def parse(value: str) -> datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        assert parse(body[0]["first_1min_candle_date"]) == datetime(2020, 2, 7, tzinfo=UTC)
        assert parse(body[0]["first_1day_candle_date"]) == datetime(1998, 1, 1, tzinfo=UTC)
        assert body[1]["first_1min_candle_date"] is None
        assert body[1]["first_1day_candle_date"] is None
    finally:
        _clear()


def test_filter_instruments_by_type() -> None:
    share = Instrument(figi="F1", ticker="AAA", instrument_type="SHARE")
    bond = Instrument(figi="F2", ticker="BBB", instrument_type="BOND")
    _override_instruments(FakeInstrumentService([share, bond]))
    try:
        with TestClient(app) as client:
            response = client.get("/api/instruments", params={"type": "SHARE"})
        assert response.status_code == 200
        body = response.json()
        assert all(item["instrument_type"] == "SHARE" for item in body)
        assert len(body) == 1
    finally:
        _clear()


def test_instrument_not_found_returns_404() -> None:
    _override_instruments(FakeInstrumentService([]))
    try:
        with TestClient(app) as client:
            response = client.get("/api/instruments/BBG004730N88")
        assert response.status_code == 404
    finally:
        _clear()


def test_market_data_candles() -> None:
    fake = TInvestFakeClient(
        responses={
            _CANDLES: {
                "candles": [
                    {
                        "open": {"units": "1", "nano": 0},
                        "high": {"units": "2", "nano": 0},
                        "low": {"units": "1", "nano": 0},
                        "close": {"units": "2", "nano": 0},
                        "volume": 5,
                        "time": "2025-01-01T10:00:00Z",
                    }
                ]
            }
        }
    )
    _override_broker(TInvestAdapter(client=fake))
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/market-data/BBG004730N88/candles",
                params={
                    "timeframe": "1h",
                    "from": "2025-01-01T00:00:00Z",
                    "to": "2025-01-02T00:00:00Z",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["volume"] == 5
        assert body[0]["figi"] == "BBG004730N88"
        assert body[0]["timeframe"] == "1h"
    finally:
        _clear()


def test_invalid_timeframe_returns_400() -> None:
    _override_broker(TInvestAdapter(client=TInvestFakeClient()))
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/market-data/BBG004730N88/candles",
                params={
                    "timeframe": "bogus",
                    "from": "2025-01-01T00:00:00Z",
                    "to": "2025-01-02T00:00:00Z",
                },
            )
        assert response.status_code == 400
    finally:
        _clear()


def test_authentication_error_returns_401() -> None:
    fake = TInvestFakeClient(errors={_GET_ACCOUNTS: AuthenticationError("bad token")})
    _override_broker(TInvestAdapter(client=fake))
    try:
        with TestClient(app) as client:
            response = client.get("/api/accounts")
        assert response.status_code == 401
    finally:
        _clear()
