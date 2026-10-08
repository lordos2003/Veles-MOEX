"""MVP-7.4 API acceptance tests (U1).

Covers, with an in-memory SQLite session and an httpx ASGI transport (no real
DB/network/token):

- U1 GET /api/accounts returns per-account ``available_cash``/``equity`` from
  GetPortfolio (the same calculation as GET /api/accounts/{id}, unchanged);
- U1 a portfolio error for one account (e.g. a closed account) does not break
  the whole list: such an account is returned with ``portfolio_available=False``
  and empty values, the other accounts keep theirs.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import Integer, MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_broker_adapter, get_session
from app.brokers import AccountNotFoundError
from app.brokers.base import BrokerAccount
from app.main import app
from app.models import Account, Base


def _sqlite_tables() -> list:
    """Clone the needed ORM tables to Integer PKs (SQLite rowid autoincrement)."""
    meta = MetaData()
    tables = []
    for table in [Account.__table__]:
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


class _AccountsBroker:
    """BrokerAdapter stand-in with a canned account list + per-account portfolios."""

    def __init__(
        self,
        accounts: list[BrokerAccount],
        portfolios: dict[str, BrokerAccount] | None = None,
        failing: set[str] | None = None,
    ) -> None:
        self._accounts = accounts
        self._portfolios = portfolios or {}
        self._failing = failing or set()

    async def get_accounts(self) -> list[BrokerAccount]:
        return self._accounts

    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        if account_id is None:
            raise AssertionError("account_id is required")
        if account_id in self._failing:
            raise AccountNotFoundError(f"Account not found: {account_id}")
        return self._portfolios[account_id]


def _account(account_id: str, name: str) -> BrokerAccount:
    return BrokerAccount(account_id=account_id, name=name, account_type="TINKOFF")


def _portfolio(account_id: str, equity: str, cash: str, currency: str = "RUB") -> BrokerAccount:
    return BrokerAccount(
        account_id=account_id,
        currency=currency,
        available_cash=Decimal(cash),
        equity=Decimal(equity),
    )


async def test_accounts_list_includes_portfolio_cash_equity(client) -> None:
    http, _ = client
    broker = _AccountsBroker(
        accounts=[_account("ext-1", "Main"), _account("ext-2", "Secondary")],
        portfolios={
            "ext-1": _portfolio("ext-1", "1250.50", "900.25"),
            "ext-2": _portfolio("ext-2", "777.77", "300.00", currency="USD"),
        },
    )
    app.dependency_overrides[get_broker_adapter] = lambda: broker
    try:
        listed = await http.get("/api/accounts")
        assert listed.status_code == 200
        rows = {a["account_id"]: a for a in listed.json()}
        assert set(rows) == {"ext-1", "ext-2"}

        first = rows["ext-1"]
        assert first["portfolio_available"] is True
        assert Decimal(first["equity"]) == Decimal("1250.50")
        assert Decimal(first["available_cash"]) == Decimal("900.25")
        assert first["currency"] == "RUB"
        # Name/type still come from GetAccounts, not the portfolio.
        assert first["name"] == "Main"
        assert first["account_type"] == "TINKOFF"

        second = rows["ext-2"]
        assert second["portfolio_available"] is True
        assert Decimal(second["equity"]) == Decimal("777.77")
        assert Decimal(second["available_cash"]) == Decimal("300.00")
        assert second["currency"] == "USD"
    finally:
        app.dependency_overrides.pop(get_broker_adapter, None)


async def test_accounts_list_one_portfolio_error_keeps_other_accounts(client) -> None:
    http, _ = client
    broker = _AccountsBroker(
        accounts=[_account("ext-1", "Main"), _account("ext-2", "Closed")],
        portfolios={"ext-1": _portfolio("ext-1", "1250.50", "900.25")},
        failing={"ext-2"},
    )
    app.dependency_overrides[get_broker_adapter] = lambda: broker
    try:
        listed = await http.get("/api/accounts")
        # A single account error must not turn the whole list into an error.
        assert listed.status_code == 200
        rows = {a["account_id"]: a for a in listed.json()}
        assert set(rows) == {"ext-1", "ext-2"}

        ok = rows["ext-1"]
        assert ok["portfolio_available"] is True
        assert Decimal(ok["equity"]) == Decimal("1250.50")

        closed = rows["ext-2"]
        assert closed["portfolio_available"] is False
        assert Decimal(closed["available_cash"]) == Decimal("0")
        assert Decimal(closed["equity"]) == Decimal("0")
        # The account itself is still listed.
        assert closed["name"] == "Closed"
    finally:
        app.dependency_overrides.pop(get_broker_adapter, None)
