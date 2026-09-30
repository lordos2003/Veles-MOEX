"""Bot persistence (broker-neutral, MVP-6.5).

The Bot is the persisted application entity. This repository loads/saves bot
state using the existing ORM ``Bot`` model and the application ``AsyncSession``.
It is the only persistence access point for the bot lifecycle; no new
persistence subsystem is introduced.

B2 (MVP-6.13 review round 1): the production live graph shares ONE long-lived
``AsyncSession`` between the stream, the scheduler passes and the API
lifecycle; an ``AsyncSession`` is not safe for concurrent use, so the
repository accepts an optional ``asyncio.Lock`` that serializes every access.
Tests and per-request API sessions (no shared session) keep the default
``None``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot
from app.models.enums import BotState


class BotRepository:
    """Load/save/update bot state from the ORM ``Bot`` model."""

    def __init__(
        self, session: AsyncSession, *, lock: asyncio.Lock | None = None
    ) -> None:
        self._session = session
        self._lock = lock

    @asynccontextmanager
    async def _session_guard(self):
        """B2: serialize access when the session is shared by concurrent owners."""
        if self._lock is not None:
            async with self._lock:
                yield
        else:
            yield

    async def get(self, bot_id: int) -> Bot | None:
        async with self._session_guard():
            return await self._session.get(Bot, bot_id)

    async def list(self) -> list[Bot]:
        async with self._session_guard():
            result = await self._session.execute(select(Bot).order_by(Bot.id))
            return list(result.scalars().all())

    async def update_state(self, bot: Bot, state: BotState) -> Bot:
        """Persist a new bot-state value on the existing ORM entity."""
        async with self._session_guard():
            bot.status = state.value
            await self._session.commit()
            await self._session.refresh(bot)
            return bot

    async def update_deposit(self, bot: Bot, deposit: Decimal | None) -> Bot:
        """Persist a new bot-deposit value on the existing ORM entity (C5)."""
        async with self._session_guard():
            bot.deposit = deposit
            await self._session.commit()
            await self._session.refresh(bot)
            return bot

    async def get_deposit(self, bot_id: int) -> Decimal | None:
        """Read the current deposit value from the database (MVP-6.11 C6).

        A deposit edit arrives through a per-request session while this
        long-lived session may already hold the ``Bot`` in its identity map
        (``expire_on_commit=False``); ``populate_existing=True`` forces a
        fresh read so the returned value is the current one, not the cached
        instance a plain ``get`` would return.
        """
        async with self._session_guard():
            bot = await self._session.get(Bot, bot_id, populate_existing=True)
            return bot.deposit if bot is not None else None
