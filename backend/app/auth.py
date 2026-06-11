"""Authentication: resolves the request to a user and binds the RLS context.

AUTH_MODE=dev      — every request is the configured dev user (local development).
AUTH_MODE=proxy    — trust the X-Forwarded-Email header set by oauth2-proxy
                     (POC deploy: Google sign-in + allowlist happen in the
                     proxy; the API must ONLY be reachable through it).
AUTH_MODE=cognito  — validates the Cognito JWT (arrives with the AWS deploy step).

Whatever the mode, the result is the same: a users row, and
`app.current_user_id` set on the request's transaction so the database's
row-level-security policies scope every subsequent query.
"""
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db


@dataclass
class CurrentUser:
    id: uuid.UUID
    email: str
    name: str | None


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> CurrentUser:
    if settings.auth_mode == "dev":
        email = settings.dev_user_email
        name = settings.dev_user_name
    elif settings.auth_mode == "proxy":
        email = request.headers.get("x-forwarded-email")
        if not email:
            raise HTTPException(status_code=401, detail="not signed in")
        name = (
            request.headers.get("x-forwarded-preferred-username")
            or email.split("@")[0]
        )
    else:
        # Cognito JWT validation lands with build sequence step 6 (AWS deploy)
        raise HTTPException(status_code=501, detail="cognito auth not configured yet")

    row = (
        await db.execute(
            text("SELECT id, email, name FROM ensure_user(:email, :name)"),
            {"email": email, "name": name},
        )
    ).one()

    # Bind the user to this transaction — RLS policies read this setting.
    await db.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(row.id)},
    )
    return CurrentUser(id=row.id, email=row.email, name=row.name)
