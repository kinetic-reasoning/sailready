from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncSession:
    """The request-scoped session, created by the middleware in main.py.

    Why middleware and not a yield-dependency: FastAPI runs yield-dependency
    teardown AFTER the response reaches the client, so a commit there loses
    the race against the browser's immediate next request (create trip ->
    'trip not found'). The middleware commits BEFORE the response is sent.

    The transaction also carries the RLS user context: auth binds the user id
    via set_config(..., is_local=true), which the row-level-security policies
    read for every query in the request.
    """
    return request.state.db
