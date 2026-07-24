from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import read_session
from app.db.models import Deal, PlatformRole, Session, User
from app.db.session import get_db

Db = Annotated[AsyncSession, Depends(get_db)]


async def current_user(
    db: Db,
    arcscrow_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = arcscrow_session
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    parsed = read_session(token or "")
    if not parsed:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    user_id, session_id = parsed
    session = await db.get(Session, session_id)
    if not session or session.user_id != user_id or session.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or revoked")
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is unavailable")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def accessible_deal(db: Db, user: CurrentUser, deal_id: UUID) -> Deal:
    query = (
        select(Deal)
        .options(selectinload(Deal.parties), selectinload(Deal.milestones))
        .where(Deal.id == deal_id)
    )
    deal = await db.scalar(query)
    if not deal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal not found")
    is_member = any(party.user_id == user.id for party in deal.parties)
    if not is_member and user.role not in {PlatformRole.ADMIN, PlatformRole.SUPER_ADMIN}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Deal membership required")
    return deal


def require_admin(user: CurrentUser) -> User:
    if user.role not in {PlatformRole.ADMIN, PlatformRole.SUPER_ADMIN}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user
