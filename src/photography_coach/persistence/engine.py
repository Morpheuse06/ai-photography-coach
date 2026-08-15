"""Async SQLAlchemy engine and session factories for the control plane.

SQLite uses NullPool because each aiosqlite connection is bound to the event
loop that created it, so pooling across request threads is unsafe. SQLite
connections also receive WAL mode, a busy timeout, and foreign-key checks.
PostgreSQL deployments can keep the same engine factory and let the pool
defaults apply.
"""

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from photography_coach.persistence.models import Base


def create_db_engine(database_url: str) -> AsyncEngine:
    """Build one async engine for the configured database URL."""
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {"timeout": 15}
    engine = create_async_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):
        _configure_sqlite(engine.sync_engine)
    return engine


def session_factory_for(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory that never expires objects after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    """Create all missing tables; used by tests and bootstrap scripts."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_schema(engine: AsyncEngine) -> None:
    """Drop every control-plane table; used only by isolated tests."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


def _configure_sqlite(sync_engine: Engine) -> None:
    @event.listens_for(sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
