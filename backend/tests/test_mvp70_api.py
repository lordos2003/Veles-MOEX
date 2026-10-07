"""MVP-7.0 API acceptance tests (R2-R7).

Covers, with an in-memory SQLite session and an httpx ASGI transport (no real
DB/network/token):

- R2 accounts sync without duplicates + local id / saved flag;
- R3 sandbox endpoints (409 when disabled, T-Invest mapping on a fake client);
- R4 strategies CRUD, immutable versions, JSON schema, validate endpoint;
- R5 bots create/patch/delete rules (STOPPED + no unclosed deal);
- R6 deal endpoints (open deal, history with close_reason);
- R7/R8 backtest API (fees/slippage mandatory, candle cap, instrument facts,
  deposit-driven grid sizing equals the live sizing computation).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import Integer, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.deps import (
    get_broker_adapter,
    get_instrument_service,
    get_market_data_service,
    get_session,
    get_settings_dep,
)
from app.brokers import TInvestAdapter
from app.brokers.base import BrokerAccount
from app.core.config import Settings
from app.domain.marketdata import Candle, Timeframe
from app.main import app
from app.models import Account, Base, Bot, Instrument, Strategy, StrategyVersion
from app.models.deal import Deal as DealRow
from app.models.deal import DealLevel as DealLevelRow
from app.strategies.config import Direction, StrategyConfig
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import GridOrder
from app.trading.sizing import deposit_to_base_nominal, round_grid_to_lot
from tests.fakes import TInvestFakeClient


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw) -> str:  # noqa: ARG001
    return "JSON"


_TABLES = [
    Account.__table__,
    Instrument.__table__,
    Strategy.__table__,
    StrategyVersion.__table__,
    Bot.__table__,
    DealRow.__table__,
    DealLevelRow.__table__,
]

# A strategy config that passes the MVP-6.12 D1 live-deal scope.
STRATEGY_CONFIG: dict = {
    "name": "grid",
    "direction": "LONG",
    "entry": {"method": "at_bar_close", "groups": []},
    "dca_grid": {"mode": "simple", "levels": 2, "spacing_percent": 0.5},
    "exit": {"take_profit": {"kind": "fixed_percentage", "percent": 2.0}},
}

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG00000000"


def _candle(i: int, open_, high, low, close) -> Candle:
    return Candle(
        figi=FIGI,
        timeframe=Timeframe.MIN_5,
        timestamp=T0 + timedelta(minutes=i * 5),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=1000,
        is_complete=True,
    )


def _sqlite_tables() -> list:
    """Clone the needed ORM tables to Integer PKs (SQLite rowid autoincrement).

    SQLite does not autoincrement a BIGINT primary key; the ORM inserts rely on
    generated ids.
    """
    meta = MetaData()
    tables = []
    for table in _TABLES:
        cloned = table.to_metadata(meta)
        for col in cloned.columns:
            if col.primary_key and isinstance(col.type, sa.BigInteger):
                col.type = Integer()
        tables.append(cloned)
    return tables


@pytest_asyncio.fixture
async def client() -> tuple[httpx.AsyncClient, AsyncSession]:
    """TestClient-equivalent (same event loop) over an in-memory SQLite session."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_sqlite_tables()))
    session = AsyncSession(engine, expire_on_commit=False)

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, session
    app.dependency_overrides.pop(get_session, None)
    await session.close()
    await engine.dispose()


async def _seed_base(session: AsyncSession) -> None:
    """Seed account/instrument/strategy v1 with explicit ids (SQLite + BigInteger)."""
    await _seed_base_with_config(session, STRATEGY_CONFIG)


async def _seed_base_with_config(session: AsyncSession, config: dict) -> None:
    """Seed account/instrument/strategy v1 with the given version config (I5)."""
    account = Account(name="main", broker="tinvest", external_account_id="ext-1")
    account.id = 1
    instrument = Instrument(
        figi=FIGI,
        ticker="SBER",
        currency="RUB",
        lot_size=10,
        tick_size=Decimal("0.10"),
        exchange="MOEX",
    )
    instrument.id = 1
    strategy = Strategy(name="grid", config={})
    strategy.id = 1
    session.add_all([account, instrument, strategy])
    await session.flush()
    version = StrategyVersion(strategy_id=1, version=1, config=config)
    version.id = 1
    session.add(version)
    await session.flush()


# --- R2: accounts ----------------------------------------------------------------


class _FakeAccountsBroker:
    """BrokerAdapter stand-in serving a canned account list."""

    def __init__(self, accounts: list[BrokerAccount]) -> None:
        self._accounts = accounts

    async def get_accounts(self) -> list[BrokerAccount]:
        return self._accounts


async def test_accounts_sync_no_duplicates_and_local_flag(client) -> None:
    http, session = client
    broker = _FakeAccountsBroker(
        [
            BrokerAccount(account_id="ext-1", name="Main"),
            BrokerAccount(account_id="ext-2", name="Secondary"),
        ]
    )
    app.dependency_overrides[get_broker_adapter] = lambda: broker
    try:
        first = await http.post("/api/accounts/sync")
        assert first.status_code == 200
        assert first.json() == {"synced": 2}

        # Second sync of the same broker accounts must not duplicate rows.
        again = await http.post("/api/accounts/sync")
        assert again.status_code == 200
        assert again.json() == {"synced": 0}

        listed = await http.get("/api/accounts")
        assert listed.status_code == 200
        accounts = listed.json()
        assert len(accounts) == 2
        for item in accounts:
            assert item["is_saved"] is True
            assert item["id"] is not None
        assert {a["account_id"] for a in accounts} == {"ext-1", "ext-2"}

        # An updated name updates the local row instead of inserting a new one.
        renamed = _FakeAccountsBroker([BrokerAccount(account_id="ext-1", name="Renamed")])
        app.dependency_overrides[get_broker_adapter] = lambda: renamed
        third = await http.post("/api/accounts/sync")
        assert third.json() == {"synced": 0}
        listed = await http.get("/api/accounts")
        rows = {a["account_id"]: a for a in listed.json()}
        assert rows["ext-1"]["name"] == "Renamed"
        # Still exactly two local rows (ext-1 updated, no duplicate inserted).
        account_rows = (await session.execute(sa.select(Account))).scalars().all()
        assert len(account_rows) == 2
    finally:
        app.dependency_overrides.pop(get_broker_adapter, None)


# --- R3: sandbox -----------------------------------------------------------------


_SANDBOX = "tinkoff.public.invest.api.contract.v1.SandboxService"


async def test_sandbox_disabled_returns_409(client) -> None:
    http, _ = client
    app.dependency_overrides[get_settings_dep] = lambda: Settings(tinvest_sandbox=False)
    app.dependency_overrides[get_broker_adapter] = lambda: TInvestAdapter(
        client=TInvestFakeClient(), sandbox=True
    )
    try:
        opened = await http.post("/api/sandbox/accounts")
        assert opened.status_code == 409

        paid = await http.post(
            "/api/sandbox/accounts/sandbox-1/pay-in",
            json={"account_id": "sandbox-1", "amount": "50000", "currency": "RUB"},
        )
        assert paid.status_code == 409

        closed = await http.delete("/api/sandbox/accounts/sandbox-1")
        assert closed.status_code == 409
    finally:
        app.dependency_overrides.pop(get_settings_dep, None)
        app.dependency_overrides.pop(get_broker_adapter, None)


async def test_sandbox_mapping_on_fake_client(client) -> None:
    http, _ = client
    fake = TInvestFakeClient(
        responses={
            f"{_SANDBOX}/OpenSandboxAccount": {"account_id": "sandbox-1"},
            f"{_SANDBOX}/SandboxPayIn": {"balance": {"units": "50000", "nano": 0}},
            f"{_SANDBOX}/CloseSandboxAccount": {},
        }
    )
    adapter = TInvestAdapter(client=fake, sandbox=True)
    app.dependency_overrides[get_settings_dep] = lambda: Settings(tinvest_sandbox=True)
    app.dependency_overrides[get_broker_adapter] = lambda: adapter
    try:
        opened = await http.post("/api/sandbox/accounts")
        assert opened.status_code == 200
        assert opened.json() == {"account_id": "sandbox-1"}

        paid = await http.post(
            "/api/sandbox/accounts/sandbox-1/pay-in",
            json={"account_id": "sandbox-1", "amount": "50000", "currency": "RUB"},
        )
        assert paid.status_code == 200
        assert paid.json() == {"account_id": "sandbox-1", "balance": "50000"}

        closed = await http.delete("/api/sandbox/accounts/sandbox-1")
        assert closed.status_code == 200
        assert closed.json() == {"account_id": "sandbox-1"}

        post_calls = [c for c in fake.calls if c[0] == f"{_SANDBOX}/OpenSandboxAccount"]
        assert post_calls == [(f"{_SANDBOX}/OpenSandboxAccount", {})]
        pay_calls = [c for c in fake.calls if c[0] == f"{_SANDBOX}/SandboxPayIn"]
        assert pay_calls == [
            (
                f"{_SANDBOX}/SandboxPayIn",
                {
                    "account_id": "sandbox-1",
                    "amount": {"currency": "RUB", "units": "50000", "nano": 0},
                },
            )
        ]
        close_calls = [c for c in fake.calls if c[0] == f"{_SANDBOX}/CloseSandboxAccount"]
        assert close_calls == [(f"{_SANDBOX}/CloseSandboxAccount", {"account_id": "sandbox-1"})]
    finally:
        app.dependency_overrides.pop(get_settings_dep, None)
        app.dependency_overrides.pop(get_broker_adapter, None)


# --- R4: strategies --------------------------------------------------------------


async def test_strategy_create_versions_schema_validate(client) -> None:
    http, _ = client
    created = await http.post(
        "/api/strategies", json={"name": "My grid", "config": STRATEGY_CONFIG}
    )
    assert created.status_code == 201
    body = created.json()
    strategy_id = body["id"]
    assert body["name"] == "My grid"
    assert body["versions"] == 1
    assert body["config"]["dca_grid"]["levels"] == 2

    # Invalid configuration -> 422 with field-level details.
    bad = {
        "name": "bad",
        "config": {**STRATEGY_CONFIG, "dca_grid": {"mode": "simple", "levels": 0}},
    }
    rejected = await http.post("/api/strategies", json=bad)
    assert rejected.status_code == 422
    locs = [e.get("loc", []) for e in rejected.json()["detail"]]
    assert any("levels" in loc for loc in locs)

    # PUT appends v2; v1 stays immutable.
    v2_config = {
        **STRATEGY_CONFIG,
        "dca_grid": {"mode": "simple", "levels": 3, "spacing_percent": 1.0},
    }
    updated = await http.put(f"/api/strategies/{strategy_id}", json={"config": v2_config})
    assert updated.status_code == 200
    assert updated.json()["versions"] == 2

    versions = await http.get(f"/api/strategies/{strategy_id}/versions")
    assert versions.status_code == 200
    rows = versions.json()
    assert [row["version"] for row in rows] == [2, 1]
    assert rows[1]["config"]["dca_grid"]["levels"] == 2  # v1 unchanged
    assert rows[0]["config"]["dca_grid"]["levels"] == 3

    # Exposing the config schema actually available for the frontend.
    schema = await http.get("/api/strategies/schema")
    assert schema.status_code == 200
    payload = schema.json()
    assert set(payload["properties"]) >= {
        "name",
        "direction",
        "entry",
        "dca_grid",
        "exit",
        "timeframe",
    }
    assert '"fixed_percentage"' in schema.text  # TP kinds are declared, not invented

    # Validate: in-scope config -> supported; trailing TP -> rejected with reason.
    ok = await http.post("/api/strategies/validate", json=STRATEGY_CONFIG)
    assert ok.status_code == 200
    assert ok.json() == {"valid": True, "live_deal": {"supported": True, "reason": None}}

    unsupported = {
        **STRATEGY_CONFIG,
        "exit": {"take_profit": {"kind": "trailing", "deviation_percent": 1.0}},
    }
    rejected_live = await http.post("/api/strategies/validate", json=unsupported)
    assert rejected_live.status_code == 200
    live = rejected_live.json()["live_deal"]
    assert live["supported"] is False
    assert "fixed_percentage" in live["reason"]


# --- MVP-7.2 I4/I5: indicator params are required ------------------------------


def _indicator_args(name: str, params: dict, **overrides) -> dict:
    arg = {"kind": "indicator", "name": name, "timeframe": "5m", "params": params}
    arg.update(overrides)
    return arg


def _config_with_indicator(arg1: dict) -> dict:
    return {
        **STRATEGY_CONFIG,
        "entry": {
            "method": "at_bar_close",
            "groups": [
                {
                    "conditions": [
                        {
                            "arg1": arg1,
                            "operator": ">",
                            "arg2": {"kind": "constant", "value": 50.0},
                        }
                    ]
                }
            ],
        },
    }


async def test_strategy_without_indicator_params_rejected_422(client) -> None:
    """I4: POST /api/strategies and /validate reject an indicator arg whose
    required period/parameter is missing — with a Russian message naming the
    indicator and the parameter (no hidden engine fallback)."""
    http, _ = client

    rsi_missing_period = _config_with_indicator(_indicator_args("RSI", {}))
    created = await http.post("/api/strategies", json={"name": "rsi", "config": rsi_missing_period})
    assert created.status_code == 422
    detail = str(created.json()["detail"])
    assert "Индикатор RSI: укажите параметр «период»" in detail
    assert "Value error" not in detail

    macd_missing_fast = _config_with_indicator(
        _indicator_args("MACD", {"slow": 26, "signal": 9})
    )
    created_macd = await http.post(
        "/api/strategies", json={"name": "macd", "config": macd_missing_fast}
    )
    assert created_macd.status_code == 422
    assert "Индикатор MACD: укажите параметр «fast»" in str(created_macd.json()["detail"])

    validated = await http.post("/api/strategies/validate", json=rsi_missing_period)
    assert validated.status_code == 422
    detail = str(validated.json()["detail"])
    assert "Индикатор RSI: укажите параметр «период»" in detail
    assert "Value error" not in detail


async def test_backtest_old_version_without_indicator_params_rejected_422(client) -> None:
    """I5: a version stored before indicator params became required fails the
    backtest with an explicit 422 (not a 500), naming indicator+param; a new
    version with the explicit parameter runs normally."""
    http, session = client
    await _seed_base_with_config(session, _config_with_indicator(_indicator_args("RSI", {})))
    version = StrategyVersion(strategy_id=1, version=2, config=_config_with_indicator(
        _indicator_args("RSI", {}, period=14)
    ))
    version.id = 2
    session.add(version)
    await session.flush()

    payload = _backtest_payload()
    del payload["config"]
    payload["strategy_version_id"] = 1
    payload["from"] = T0.isoformat()
    payload["to"] = (T0 + timedelta(hours=1)).isoformat()

    candles = [
        _candle(0, 100, 100.5, 99.5, 100.0),
        _candle(1, 100.5, 101, 100, 100.8),
        _candle(2, 100.8, 111, 100.5, 110.5),
    ]
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: _FakeMarketData(candles)
    try:
        old = await http.post("/api/backtests", json=payload)
        assert old.status_code == 422
        assert "Индикатор RSI: укажите параметр «период»" in str(old.json()["detail"])

        payload["strategy_version_id"] = 2
        fixed = await http.post("/api/backtests", json=payload)
        assert fixed.status_code == 200
    finally:
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)


# --- R5: bots --------------------------------------------------------------------


async def test_bot_create_patch_delete_rules(client) -> None:
    http, session = client
    await _seed_base(session)
    second = StrategyVersion(strategy_id=1, version=2, config={**STRATEGY_CONFIG})
    second.id = 2
    session.add(second)
    await session.flush()

    def payload(**overrides) -> dict:
        base = {"name": "bot-1", "strategy_version_id": 1, "account_id": 1, "instrument_id": 1}
        base.update(overrides)
        return base

    created = await http.post("/api/bots", json=payload(deposit="50000"))
    assert created.status_code == 201
    bot = created.json()
    assert bot["status"] == "STOPPED"
    assert Decimal(bot["deposit"]) == Decimal("50000")
    bot_id = bot["id"]

    # Missing referenced entities -> explicit 404.
    for overrides in (
        {"strategy_version_id": 999},
        {"account_id": 999},
        {"instrument_id": 999},
    ):
        missing = await http.post("/api/bots", json=payload(**overrides))
        assert missing.status_code == 404

    # Empty PATCH is a client error (422), not a silent no-op.
    empty = await http.patch(f"/api/bots/{bot_id}", json={})
    assert empty.status_code == 422

    # Strategy version may change while STOPPED with no unclosed deal.
    changed = await http.patch(f"/api/bots/{bot_id}", json={"strategy_version_id": 2})
    assert changed.status_code == 200
    assert changed.json()["strategy_version_id"] == 2

    # Changing to a missing version -> 404.
    missing_version = await http.patch(f"/api/bots/{bot_id}", json={"strategy_version_id": 999})
    assert missing_version.status_code == 404

    # A STOPPED bot without a deal may be deleted.
    deleted = await http.delete(f"/api/bots/{bot_id}")
    assert deleted.status_code == 200


async def test_bot_version_change_blocked_running_or_open_deal(client) -> None:
    http, session = client
    await _seed_base(session)

    async def seed_bot(status: str, bot_id: int) -> int:
        bot = Bot(
            name="locked", strategy_version_id=1, account_id=1, instrument_id=1, status=status
        )
        bot.id = bot_id
        session.add(bot)
        await session.flush()
        return bot.id

    running = await seed_bot("RUNNING", 20)

    running_patch = await http.patch(f"/api/bots/{running}", json={"strategy_version_id": 1})
    assert running_patch.status_code == 409
    running_delete = await http.delete(f"/api/bots/{running}")
    assert running_delete.status_code == 409

    stopped = await seed_bot("STOPPED", 21)
    deal = DealRow(
        bot_id=stopped,
        instrument_figi=FIGI,
        direction=Direction.LONG.value,
        status="OPEN",
        base_nominal=Decimal("50000"),
    )
    deal.id = 1
    session.add(deal)
    await session.flush()

    open_deal_patch = await http.patch(f"/api/bots/{stopped}", json={"strategy_version_id": 1})
    assert open_deal_patch.status_code == 409
    assert "unclosed deal" in open_deal_patch.json()["detail"]
    open_deal_delete = await http.delete(f"/api/bots/{stopped}")
    assert open_deal_delete.status_code == 409


# --- R6: deals -------------------------------------------------------------------


async def test_deal_endpoints_open_and_history(client) -> None:
    http, session = client
    await _seed_base(session)
    bot = Bot(name="deals", strategy_version_id=1, account_id=1, instrument_id=1, status="STOPPED")
    bot.id = 1
    session.add(bot)
    await session.flush()

    # No deal yet -> HTTP 200 with null body.
    no_deal = await http.get("/api/bots/1/deal")
    assert no_deal.status_code == 200
    assert no_deal.json() is None
    assert (await http.get("/api/bots/1/deals")).json() == []

    # One open deal (grid level + TP + stop state).
    open_deal = DealRow(
        bot_id=1,
        instrument_figi=FIGI,
        direction=Direction.LONG.value,
        status="OPEN",
        base_nominal=Decimal("50000"),
        reference_price=Decimal("100"),
        lot_size=10,
        tick_size=Decimal("0.10"),
        tp_percent=Decimal("2"),
        average_price=Decimal("100"),
        tp_price=Decimal("102"),
        tp_quantity=Decimal("10"),
        sl_percent=Decimal("1"),
        sl_price=Decimal("99"),
        sl_quantity=Decimal("10"),
        sl_order_id="sl-1",
    )
    open_deal.id = 1
    level = DealLevelRow(
        deal_id=1,
        level_index=0,
        side="BUY",
        price=Decimal("100"),
        nominal=Decimal("25000"),
        quantity=Decimal("10"),
        offset_percent=Decimal("0"),
        status="filled",
        is_market=True,
        filled_quantity=Decimal("10"),
    )
    level.id = 1
    session.add_all([open_deal, level])
    await session.flush()

    current = await http.get("/api/bots/1/deal")
    assert current.status_code == 200
    body = current.json()
    assert body["status"] == "OPEN"
    assert Decimal(body["tp_price"]) == Decimal("102")
    assert Decimal(body["tp_quantity"]) == Decimal("10")
    assert body["sl_order_id"] == "sl-1"
    assert Decimal(body["sl_price"]) == Decimal("99")
    assert body["sl_active"] is True  # stop order placed
    assert Decimal(body["position_quantity"]) == Decimal("10")  # filled level
    assert len(body["levels"]) == 1
    assert body["levels"][0]["side"] == "BUY"
    assert Decimal(body["levels"][0]["quantity"]) == Decimal("10")
    assert Decimal(body["levels"][0]["filled_quantity"]) == Decimal("10")

    # Closed history: newest first, close_reason included, limit works.
    closed_older = DealRow(
        bot_id=1,
        instrument_figi=FIGI,
        direction=Direction.LONG.value,
        status="CLOSED",
        base_nominal=Decimal("50000"),
        reference_price=Decimal("100"),
        close_reason="take_profit",
        created_at=T0 - timedelta(hours=2),
        closed_at=T0 - timedelta(hours=2),
    )
    closed_older.id = 2
    closed_newer = DealRow(
        bot_id=1,
        instrument_figi=FIGI,
        direction=Direction.LONG.value,
        status="CLOSED",
        base_nominal=Decimal("50000"),
        reference_price=Decimal("100"),
        close_reason="stop_loss",
        created_at=T0 - timedelta(hours=1),
        closed_at=T0 - timedelta(hours=1),
    )
    closed_newer.id = 3
    session.add_all([closed_older, closed_newer])
    await session.flush()

    history = await http.get("/api/bots/1/deals")
    assert history.status_code == 200
    reasons = [row["close_reason"] for row in history.json()]
    assert reasons == ["stop_loss", "take_profit"]

    limited = await http.get("/api/bots/1/deals?limit=1")
    assert len(limited.json()) == 1
    assert limited.json()[0]["close_reason"] == "stop_loss"

    unknown = await http.get("/api/bots/999/deal")
    assert unknown.status_code == 404


# --- R7/R8: backtest -------------------------------------------------------------


class _FakeInstrumentService:
    """InstrumentService stand-in serving one instrument row."""

    def __init__(self, instrument: Instrument) -> None:
        self._instrument = instrument

    async def get_by_id(self, instrument_id: int) -> Instrument | None:
        return self._instrument if instrument_id == self._instrument.id else None


class _FakeMarketData:
    """MarketDataService stand-in returning fixed candles."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    async def get_candles(self, figi, timeframe, from_, to) -> list[Candle]:
        return self._candles


def _instrument(**overrides) -> Instrument:
    fields = dict(
        figi=FIGI,
        ticker="SBER",
        currency="RUB",
        lot_size=10,
        tick_size=Decimal("0.10"),
    )
    fields.update(overrides)
    instrument = Instrument(**fields)
    instrument.id = 1
    return instrument


def _backtest_payload(**overrides) -> dict:
    payload = {
        "config": STRATEGY_CONFIG,
        "instrument_id": 1,
        "timeframe": "5m",
        "from": T0.isoformat(),
        "to": (T0 + timedelta(hours=1)).isoformat(),
        "deposit": "50000",
        "maker_fee": "0.0003",
        "taker_fee": "0.0003",
        "slippage": "0",
    }
    payload.update(overrides)
    return payload


async def test_backtest_run_on_fake_candles(client) -> None:
    http, _ = client
    candles = [
        _candle(0, 100, 100.5, 99.5, 100.0),  # c0 close -> signal
        _candle(1, 100.5, 101, 100, 100.8),  # c1 open -> entry
        _candle(2, 100.8, 111, 100.5, 110.5),  # TP 2% = 102.51 hit
    ]
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: _FakeMarketData(candles)
    try:
        response = await http.post("/api/backtests", json=_backtest_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["num_trades"] == 1
        assert body["deals"][0]["reason"] == "fixed_tp"
        assert body["deals"][0]["direction"] == "LONG"
        assert Decimal(body["deals"][0]["entry_price"]) == Decimal("100.5")
        assert Decimal(body["total_fees"]) > 0
        assert body["executions"][0]["quantity"] == "240.0"  # 24 whole lots (R8)
        assert body["executions"][0]["instrument_figi"] == FIGI
        assert len(body["orders"]) >= 1
    finally:
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)


async def test_backtest_missing_fees_rejected(client) -> None:
    http, _ = client
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: _FakeMarketData([])
    try:
        payload = _backtest_payload()
        del payload["maker_fee"]
        del payload["taker_fee"]
        response = await http.post("/api/backtests", json=payload)
        assert response.status_code == 422

        # Both strategy sources or none -> 422 as well.
        both = await http.post(
            "/api/backtests", json=_backtest_payload(strategy_version_id=1)
        )
        assert both.status_code == 422
    finally:
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)


async def test_backtest_candle_cap_and_instrument_facts(client) -> None:
    http, _ = client
    candles = [_candle(i, 100, 101, 99, 100) for i in range(11)]
    app.dependency_overrides[get_settings_dep] = lambda: Settings(backtest_max_candles=10)
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: _FakeMarketData(candles)
    try:
        exceeded = await http.post("/api/backtests", json=_backtest_payload())
        assert exceeded.status_code == 422
        assert "backtest_max_candles" in exceeded.json()["detail"]

        # Instrument without lot/tick facts -> explicit error, no default.
        for overrides in ({"lot_size": None}, {"tick_size": None}):
            app.dependency_overrides[get_instrument_service] = (
                lambda o=overrides: _FakeInstrumentService(_instrument(**o))
            )
            response = await http.post("/api/backtests", json=_backtest_payload())
            assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_settings_dep, None)
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)


async def test_backtest_initial_capital_is_deposit(client) -> None:
    """B1 (review round 1): the run capital is the request deposit, not an
    invented 10 000 — initial_capital / final_capital / roi derive from it."""
    http, _ = client
    candles = [
        _candle(0, 100, 100.5, 99.5, 100.0),
        _candle(1, 100.5, 101, 100, 100.8),
        _candle(2, 100.8, 111, 100.5, 110.5),  # TP 2% = 102.51 hit
    ]
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: _FakeMarketData(candles)
    try:
        deposit = "50000"
        response = await http.post("/api/backtests", json=_backtest_payload(deposit=deposit))
        assert response.status_code == 200
        body = response.json()
        initial = Decimal(body["initial_capital"])
        net = Decimal(body["net_pnl"])
        assert initial == Decimal(deposit)
        assert Decimal(body["final_capital"]) == initial + net
        assert Decimal(body["roi"]) == net / initial
    finally:
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)


async def test_backtest_candle_precheck_before_broker(client) -> None:
    """B2 (review round 1): an oversized period is rejected BEFORE any broker
    request (the MarketDataService must not be called)."""
    http, _ = client

    class _NeverCalledMarketData:
        def __init__(self) -> None:
            self.calls = 0

        async def get_candles(self, figi, timeframe, from_, to) -> list[Candle]:
            self.calls += 1
            return []

    market = _NeverCalledMarketData()
    app.dependency_overrides[get_settings_dep] = lambda: Settings(backtest_max_candles=10000)
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: market
    try:
        # 1m over two calendar years: the estimate is far above the cap.
        payload = _backtest_payload(
            **{
                "timeframe": "1m",
                "from": (T0 - timedelta(days=730)).isoformat(),
            }
        )
        response = await http.post("/api/backtests", json=payload)
        assert response.status_code == 422
        assert "backtest_max_candles" in response.json()["detail"]
        assert market.calls == 0
    finally:
        app.dependency_overrides.pop(get_settings_dep, None)
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)


async def test_backtest_strategy_timeframe_must_match(client) -> None:
    """B3 (review round 1): the request timeframe must equal the strategy's own
    (a mismatch would evaluate its indicators on another interval than live)."""
    http, _ = client
    candles = [
        _candle(0, 100, 100.5, 99.5, 100.0),
        _candle(1, 100.5, 101, 100, 100.8),
        _candle(2, 100.8, 111, 100.5, 110.5),
    ]
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: _FakeMarketData(candles)
    try:
        mismatched = await http.post(
            "/api/backtests", json=_backtest_payload(config={**STRATEGY_CONFIG, "timeframe": "1h"})
        )
        assert mismatched.status_code == 422
        assert "timeframe" in mismatched.json()["detail"]

        # Same timeframe as the strategy -> the run succeeds.
        matched = await http.post(
            "/api/backtests", json=_backtest_payload(config={**STRATEGY_CONFIG, "timeframe": "5m"})
        )
        assert matched.status_code == 200
    finally:
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)


def _expected_grid_quantities(
    config: StrategyConfig, deposit: Decimal, entry_price: Decimal, lot_size: int
) -> list[Decimal]:
    """Live sizing contract (C2 + C3): the expected grid order quantities."""
    base_nominal = deposit_to_base_nominal(deposit, config.dca_grid)
    state = DCAGridEngine().build(
        config.dca_grid, entry_price, config.direction, base_nominal=base_nominal
    )
    plans = [
        GridOrder(
            side=level.side,
            quantity=float(level.quantity),
            price=None if level.is_market else float(level.price),
            offset_percent=level.offset_percent,
            nominal=float(level.nominal),
        )
        for level in state.levels
    ]
    rounded = round_grid_to_lot(plans, lot_size=lot_size, currency="RUB")
    return [Decimal(str(order.quantity)) for order in rounded]


async def test_backtest_deposit_grid_matches_live_sizing(client) -> None:
    """R8: grid quantities from the backtest equal the live sizing math and
    are whole lots (rounded down)."""
    http, _ = client
    candles = [
        _candle(0, 100, 100.5, 99.5, 100.0),
        _candle(1, 100.5, 101, 100, 100.8),
        _candle(2, 100.8, 111, 100.5, 110.5),
    ]
    app.dependency_overrides[get_instrument_service] = lambda: _FakeInstrumentService(_instrument())
    app.dependency_overrides[get_market_data_service] = lambda: _FakeMarketData(candles)
    try:
        for config in (
            # SIMPLE: 3 levels, D / sum(k**i) base nominal.
            {
                **STRATEGY_CONFIG,
                "dca_grid": {"mode": "simple", "levels": 3, "spacing_percent": 1.0},
            },
            # CUSTOM: explicit percentages summing to 100% of the deposit.
            {
                **STRATEGY_CONFIG,
                "dca_grid": {
                    "mode": "custom",
                    "custom_levels": [
                        {"offset_percent": 0.0, "nominal_percent": 60.0},
                        {"offset_percent": 1.0, "nominal_percent": 40.0},
                    ],
                },
            },
        ):
            staged = StrategyConfig.model_validate(config)
            expected = _expected_grid_quantities(staged, Decimal("50000"), Decimal("100.5"), 10)
            assert expected[0] > 0

            response = await http.post(
                "/api/backtests", json=_backtest_payload(config=config)
            )
            assert response.status_code == 200
            body = response.json()

            # Level 0 is the market entry; remaining DCA levels are BUY limits.
            entry = body["executions"][0]
            assert Decimal(entry["quantity"]) == expected[0]
            dca_orders = [
                order
                for order in body["orders"]
                if order["type"] == "LIMIT" and order["side"] == "BUY"
            ]
            got = [Decimal(order["requested_quantity"]) for order in dca_orders]
            assert got == expected[1:]

            # Whole lots everywhere (rounded down: nominal/price >= qty * lot).
            for quantity in [Decimal(entry["quantity"])] + got:
                assert quantity % 10 == 0, quantity

        # SIGNAL mode sizing is explicitly unsupported (no limit invented).
        signal_config = {
            **STRATEGY_CONFIG,
            "dca_grid": {"mode": "signal", "levels": 1},
        }
        rejected = await http.post(
            "/api/backtests", json=_backtest_payload(config=signal_config)
        )
        assert rejected.status_code == 422
        assert "SIGNAL" in rejected.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_instrument_service, None)
        app.dependency_overrides.pop(get_market_data_service, None)
