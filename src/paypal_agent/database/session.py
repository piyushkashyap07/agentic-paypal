from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from paypal_agent.config import settings
from paypal_agent.database.models import Base

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None
_ready = False


def get_factory() -> async_sessionmaker[AsyncSession]:
    """Create the engine on first use so tests can point at a temp database."""

    global _engine, _factory

    if _factory is None:
        _engine = create_async_engine(settings.database_url)
        _factory = async_sessionmaker(_engine, expire_on_commit=False)

    return _factory


async def init_db() -> None:
    """Create the tables if they don't exist yet. Safe to call repeatedly."""

    global _ready

    get_factory()

    if _ready:
        return

    async with _engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    _ready = True


async def close_db() -> None:
    global _engine, _factory, _ready

    if _engine is not None:
        await _engine.dispose()

    _engine = _factory = None
    _ready = False
