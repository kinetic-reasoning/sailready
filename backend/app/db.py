from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session + transaction per request.

    The transaction matters beyond atomicity: the authenticated user id is
    bound to it via set_config(..., is_local=true), which is what the
    row-level-security policies read. Commit on success, rollback on error.
    """
    async with SessionLocal() as session:
        async with session.begin():
            yield session
