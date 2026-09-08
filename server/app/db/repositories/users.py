"""Identity queries use immutable provider subjects and eagerly load the user."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AuthIdentity, User
from app.models.enums import AuthProvider


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def google_identity(session: AsyncSession, subject: str) -> AuthIdentity | None:
    existing = await session.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.provider == AuthProvider.GOOGLE,
            AuthIdentity.provider_user_id == subject,
        )
        .options(selectinload(AuthIdentity.user))
    )
    return existing


async def email_owner(session: AsyncSession, email: str) -> uuid.UUID | None:
    return await session.scalar(select(User.id).where(User.email == email))


async def other_email_owner(
    session: AsyncSession, email: str, user_id: uuid.UUID
) -> uuid.UUID | None:
    return await session.scalar(select(User.id).where(User.email == email, User.id != user_id))


async def add_user(session: AsyncSession, user: User) -> None:
    session.add(user)


async def add_identity(session: AsyncSession, identity: AuthIdentity) -> None:
    session.add(identity)
