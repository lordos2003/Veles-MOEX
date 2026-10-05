"""Account service / repository.

Local source of truth for broker accounts bound to the platform (PostgreSQL).
The broker adapter hands out normalized ``BrokerAccount`` objects; this service
upserts them and reads them back, guaranteeing a single local row per
(broker, external_account_id).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import BrokerAccount
from app.models.account import Account


class AccountService:
    """Read/write account access bound to an async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[Account]:
        result = await self._session.execute(select(Account).order_by(Account.id))
        return list(result.scalars())

    async def get_by_id(self, account_id: int) -> Account | None:
        return await self._session.get(Account, account_id)

    async def get_local(self, external_account_id: str, broker: str = "tinvest") -> Account | None:
        """Return the local account row for a broker account, or ``None``."""
        statement = select(Account).where(
            Account.external_account_id == external_account_id,
            Account.broker == broker,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def local_by_broker_ids(
        self, external_account_ids: list[str], broker: str = "tinvest"
    ) -> dict[str, int]:
        """Map broker external account ids to local ids for the given broker."""
        if not external_account_ids:
            return {}
        statement = select(Account.external_account_id, Account.id).where(
            Account.external_account_id.in_(external_account_ids),
            Account.broker == broker,
        )
        result = await self._session.execute(statement)
        return {external: local_id for external, local_id in result.all()}

    async def sync_from_broker(self, accounts: list[BrokerAccount]) -> int:
        """Upsert broker accounts by (broker, external_account_id), no duplicates.

        Broker accounts that are already saved locally are matched by
        ``external_account_id`` and updated (name/broker). Untracked accounts
        are inserted. Deleted/absent broker accounts are not touched.
        Returns the number of locally tracked accounts after the sync.
        """
        count = 0
        for broker_account in accounts:
            if not broker_account.account_id:
                continue
            existing = await self.get_local(broker_account.account_id, broker_account.broker)
            if existing is None:
                self._session.add(
                    Account(
                        name=broker_account.name or broker_account.account_id,
                        broker=broker_account.broker,
                        external_account_id=broker_account.account_id,
                        is_active=True,
                    )
                )
                count += 1
            else:
                if broker_account.name:
                    existing.name = broker_account.name
                if not existing.is_active:
                    existing.is_active = True
        await self._session.flush()
        return count
