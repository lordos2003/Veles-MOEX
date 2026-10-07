"""MVP-7.1 REV1 review fixes (B1): write paths must commit the transaction.

The MVP-7.0 API tests exercise the API and the request session through the
same in-memory session, so a missing ``commit()`` was invisible there: flush
data was readable from the same session. B1 checks persistence with a fresh
session *after* the request completed and its session closed — on a file-based
SQLite database where an uncommitted transaction of another connection is not
visible.
"""

from __future__ import annotations

import httpx
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_broker_adapter, get_session
from app.brokers.base import BrokerAccount
from app.main import app
from app.models import Account, Base, Strategy, StrategyVersion
from app.strategies.config import StrategyConfig
from tests.test_mvp70_api import STRATEGY_CONFIG, _FakeAccountsBroker, _sqlite_tables


@pytest_asyncio.fixture
async def file_client(tmp_path):
    """API client over a file-based SQLite DB + one fresh session per request.

    A fresh session per request (instead of one shared session) means data is
    visible after the request only if the write path committed.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_sqlite_tables()))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        yield factory, engine
    finally:
        app.dependency_overrides.pop(get_session, None)
        await engine.dispose()


async def _get(factory: async_sessionmaker[AsyncSession], model, *where):
    async with factory() as session:
        result = await session.execute(select(model).where(*where))
        return result.scalars().first()


async def _except_single(factory: async_sessionmaker[AsyncSession], model, *where):
    """Assert exactly one matching row and return it."""
    async with factory() as session:
        result = await session.execute(select(model).where(*where))
        rows = list(result.scalars())
        assert len(rows) == 1, f"expected exactly one {model.__name__}, got {len(rows)}"
        return rows[0]


async def _versions(factory: async_sessionmaker[AsyncSession], strategy_id: int):
    """Return all strategy versions, newest first."""
    async with factory() as session:
        result = await session.execute(
            select(StrategyVersion)
            .where(StrategyVersion.strategy_id == strategy_id)
            .order_by(StrategyVersion.version.desc())
        )
        return list(result.scalars())


async def test_strategy_create_persists_across_sessions(file_client) -> None:
    factory, _ = file_client
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        res = await http.post(
            "/api/strategies",
            json={"name": "persisted", "config": STRATEGY_CONFIG},
        )
        assert res.status_code == 201, res.text
        strategy_id = res.json()["id"]

    # A brand-new session must see the row committed by the request session.
    strategy = await _get(factory, Strategy, Strategy.id == strategy_id)
    assert strategy is not None
    assert strategy.name == "persisted"

    version = await _except_single(
        factory, StrategyVersion, StrategyVersion.strategy_id == strategy_id
    )
    assert version.version == 1
    assert StrategyConfig.model_validate(version.config).model_dump() == StrategyConfig(
        **STRATEGY_CONFIG
    ).model_dump()


async def test_strategy_update_appends_persisted_version(file_client) -> None:
    factory, _ = file_client
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        res = await http.post(
            "/api/strategies",
            json={"name": "persisted", "config": STRATEGY_CONFIG},
        )
        assert res.status_code == 201, res.text
        strategy_id = res.json()["id"]

        updated = dict(STRATEGY_CONFIG)
        updated["dca_grid"] = dict(updated["dca_grid"], levels=3)
        res = await http.put(f"/api/strategies/{strategy_id}", json={"config": updated})
        assert res.status_code == 200, res.text
        assert res.json()["versions"] == 2

    versions = await _versions(factory, strategy_id)
    assert [v.version for v in versions] == [2, 1]
    assert versions[0].config["dca_grid"]["levels"] == 3


async def test_account_sync_persists_across_sessions(file_client) -> None:
    factory, _ = file_client
    broker = _FakeAccountsBroker(
        [BrokerAccount(account_id="ext-ns", name="New Session")]
    )
    app.dependency_overrides[get_broker_adapter] = lambda: broker
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            res = await http.post("/api/accounts/sync")
            assert res.status_code == 200, res.text
    finally:
        app.dependency_overrides.pop(get_broker_adapter, None)

    account = await _get(factory, Account, Account.external_account_id == "ext-ns")
    assert account is not None
    assert account.name == "New Session"
