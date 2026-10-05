"""Strategy repository/service (MVP-7.0 R4).

A Strategy is configuration/data. Creating a strategy writes the initial
immutable version (v1); updating the configuration appends a new immutable
version (max + 1). Existing versions are never mutated, so backtests and bots
always reference a reproducible snapshot.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import Strategy, StrategyVersion
from app.strategies.config import StrategyConfig


class StrategyNotFoundError(LookupError):
    """The requested strategy or version does not exist."""


class StrategyService:
    """Read/write strategy access bound to an async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, name: str, config: StrategyConfig, description: str | None = None
    ) -> Strategy:
        """Create a strategy with its initial version (v1)."""
        strategy = Strategy(
            name=name,
            description=description,
            is_active=True,
            config={},
        )
        self._session.add(strategy)
        await self._session.flush()
        self._session.add(
            StrategyVersion(
                strategy_id=strategy.id,
                version=1,
                config=config.model_dump(mode="json"),
            )
        )
        await self._session.flush()
        strategy.config = config.model_dump(mode="json")
        return strategy

    async def get(self, strategy_id: int) -> Strategy | None:
        return await self._session.get(Strategy, strategy_id)

    async def list(self) -> list[Strategy]:
        result = await self._session.execute(
            select(Strategy).order_by(Strategy.id.desc())
        )
        return list(result.scalars())

    async def get_version(self, version_id: int) -> StrategyVersion | None:
        return await self._session.get(StrategyVersion, version_id)

    async def versions(self, strategy_id: int) -> list[StrategyVersion]:
        result = await self._session.execute(
            select(StrategyVersion)
            .where(StrategyVersion.strategy_id == strategy_id)
            .order_by(StrategyVersion.version.desc())
        )
        return list(result.scalars())

    async def latest_version(self, strategy_id: int) -> StrategyVersion | None:
        result = await self._session.execute(
            select(StrategyVersion)
            .where(StrategyVersion.strategy_id == strategy_id)
            .order_by(StrategyVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def next_version_number(self, strategy_id: int) -> int:
        result = await self._session.execute(
            select(func.max(StrategyVersion.version)).where(
                StrategyVersion.strategy_id == strategy_id
            )
        )
        max_version = result.scalar_one_or_none()
        return int(max_version or 0) + 1

    async def update(
        self,
        strategy_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        config: StrategyConfig | None = None,
    ) -> Strategy:
        """Update strategy metadata; a new config creates the next version."""
        strategy = await self.get(strategy_id)
        if strategy is None:
            raise StrategyNotFoundError(f"strategy {strategy_id} not found")
        if name is not None:
            strategy.name = name
        if description is not None:
            strategy.description = description
        if config is not None:
            version = await self.next_version_number(strategy_id)
            self._session.add(
                StrategyVersion(
                    strategy_id=strategy.id,
                    version=version,
                    config=config.model_dump(mode="json"),
                )
            )
            strategy.config = config.model_dump(mode="json")
        await self._session.flush()
        return strategy
