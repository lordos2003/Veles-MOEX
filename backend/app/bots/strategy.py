"""Bot strategy loading (broker-neutral, MVP-6.7).

A Bot references an immutable ``StrategyVersion``. This module is the minimum
repository/service boundary that loads the referenced version and validates its
stored configuration through the existing ``StrategyConfig`` model. It never
mutates a ``StrategyVersion`` and never invents financial defaults: a missing
or invalid configuration blocks execution explicitly via |StrategyLoadError|.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot
from app.models.strategy import StrategyVersion
from app.strategies.config import StrategyConfig


class StrategyLoadError(RuntimeError):
    """Raised when a bot's strategy version is missing or invalid."""


@dataclass(frozen=True)
class BotStrategy:
    """An immutable, validated strategy bound to a bot's strategy version."""

    strategy_version_id: int
    version: int
    config: StrategyConfig


async def load_bot_strategy(session: AsyncSession, bot: Bot) -> BotStrategy:
    """Load and validate the strategy version referenced by ``bot``.

    Raises |StrategyLoadError| when the referenced version does not exist or
    its stored configuration does not validate against ``StrategyConfig``.
    """
    version = await session.get(StrategyVersion, bot.strategy_version_id)
    if version is None:
        raise StrategyLoadError(
            f"bot {bot.id} references strategy version {bot.strategy_version_id} "
            "which does not exist"
        )
    try:
        config = StrategyConfig.model_validate(version.config)
    except ValidationError as exc:
        raise StrategyLoadError(
            f"strategy version {version.id} (v{version.version}) has an invalid "
            f"configuration: {exc}"
        ) from exc
    return BotStrategy(
        strategy_version_id=version.id,
        version=version.version,
        config=config,
    )


async def load_bot_strategy_by_id(session: AsyncSession, bot_id: int) -> BotStrategy:
    """Load the strategy version of the bot with ``bot_id``."""
    bot = await session.get(Bot, bot_id)
    if bot is None:
        raise StrategyLoadError(f"bot {bot_id} not found")
    return await load_bot_strategy(session, bot)
