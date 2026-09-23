"""Bot persistence (broker-neutral, MVP-6.5).

The Bot is the persisted application entity. This repository loads/saves bot
state using the existing ORM ``Bot`` model and the application ``AsyncSession``.
It is the only persistence access point for the bot lifecycle; no new
persistence subsystem is introduced.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot
from app.models.enums import BotState


class BotRepository:
    """Load/save/update bot state from the ORM ``Bot`` model."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, bot_id: int) -> Bot | None:
        return await self._session.get(Bot, bot_id)

    async def list(self) -> list[Bot]:
        result = await self._session.execute(select(Bot).order_by(Bot.id))
        return list(result.scalars().all())

    async def update_state(self, bot: Bot, state: BotState) -> Bot:
        """Persist a new bot-state value on the existing ORM entity."""
        bot.status = state.value
        await self._session.commit()
        await self._session.refresh(bot)
        return bot
