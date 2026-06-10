from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import boats, conditions, feedback, notifications, routes, scores, trips, users
from app.db import SessionLocal, engine

app = FastAPI(title="SailReady API", version="0.1.0")


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """Request-scoped DB session, committed BEFORE the response is sent so the
    client's next request always sees this request's writes (see db.get_db)."""
    async with SessionLocal() as session:
        request.state.db = session
        try:
            response = await call_next(request)
        except Exception:
            await session.rollback()
            raise
        if response.status_code >= 400:
            await session.rollback()
        else:
            await session.commit()
        return response

API_PREFIX = "/api/v1"
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(boats.router, prefix=API_PREFIX)
app.include_router(trips.router, prefix=API_PREFIX)
app.include_router(scores.router, prefix=API_PREFIX)
app.include_router(routes.router, prefix=API_PREFIX)
app.include_router(feedback.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(conditions.router, prefix=API_PREFIX)

# Prototype map UI (the real React PWA arrives in build step 5)
app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="app")


# Starlette's HTTPException is the base class — registering the handler there
# catches both route-raised fastapi.HTTPException and framework-level 404/405s,
# so ALL errors ship in the same {data, error} envelope as success responses.
@app.exception_handler(StarletteHTTPException)
async def http_exception_envelope(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "error": {"code": str(exc.status_code), "message": str(exc.detail)},
        },
    )


@app.get("/")
async def root() -> dict:
    return {
        "name": "SailReady API",
        "version": app.version,
        "app": "/app",
        "docs": "/docs",
        "health": "/healthz",
        "api": API_PREFIX,
    }


@app.get("/healthz")
async def healthz() -> dict:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
