"""Turning a verified external identity into a local user."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AuthIdentity, User
from app.enums import AuthProvider
from app.services.google_oauth import GoogleIdentity


class EmailAlreadyRegisteredError(Exception):
    """The address belongs to an account reached through a different provider.

    Raised instead of linking the two, and instead of letting the unique index
    surface as a 500. The caller turns it into a 409 telling the user which way
    in they already have.
    """

    def __init__(self, email: str) -> None:
        super().__init__(f"{email} is already registered with a different sign-in method")
        self.email = email


@dataclass(frozen=True, slots=True)
class ResolvedUser:
    user: User
    is_new_user: bool


async def upsert_google_user(session: AsyncSession, identity: GoogleIdentity) -> ResolvedUser:
    """Find or create the user behind a verified Google identity.

    Matching is on ``(provider, provider_user_id)`` — Google's immutable subject
    — never on email, in either direction. A user can change their Google
    address, so email is a mirror kept for display, never the thing that
    resolves identity: matching on it would both lose someone their account and
    let a reclaimed address take over another.
    """
    existing = await session.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.provider == AuthProvider.GOOGLE,
            AuthIdentity.provider_user_id == identity.subject,
        )
        .options(selectinload(AuthIdentity.user))
    )

    now = datetime.now(UTC)

    if existing is not None:
        existing.last_login_at = now
        existing.email = identity.email
        user = existing.user
        # Keep the local mirror fresh, but never overwrite a name the user has
        # since edited on their profile with Google's version.
        if identity.email != user.email:
            # Someone else may already hold the new address — the user swapped
            # to an address another account was opened with. The unique index
            # would raise mid-request and present as a 500 on sign-in, so check
            # first and simply keep the old mirror. Identity is the Google
            # subject, not the address, so the session is unaffected either way.
            clash = await session.scalar(
                select(User.id).where(User.email == identity.email, User.id != user.id)
            )
            if clash is None:
                user.email = identity.email
        if identity.picture:
            user.avatar_url = identity.picture
        await session.commit()
        await session.refresh(user)
        return ResolvedUser(user=user, is_new_user=False)

    # No identity row: a new person, even when the address already belongs to an
    # account. Auto-linking on a matching email is the obvious shortcut and it is
    # an account-takeover vector — whoever holds an address when a second
    # provider is added inherits the account behind it. Google happens to verify
    # its addresses, but that guarantee lives in the verifier, not here, and the
    # first provider that issues a relay address (or does not verify at all)
    # turns the shortcut into a way in. Attaching a second provider to an
    # existing account is a decision a signed-in user makes deliberately.
    taken = await session.scalar(select(User.id).where(User.email == identity.email))
    if taken is not None:
        raise EmailAlreadyRegisteredError(identity.email)

    user = User(
        email=identity.email,
        first_name=identity.first_name,
        last_name=identity.last_name,
        avatar_url=identity.picture,
    )
    session.add(user)
    await session.flush()

    session.add(
        AuthIdentity(
            user_id=user.id,
            provider=AuthProvider.GOOGLE,
            provider_user_id=identity.subject,
            email=identity.email,
            last_login_at=now,
        )
    )

    await session.commit()
    await session.refresh(user)
    return ResolvedUser(user=user, is_new_user=True)


async def has_completed_onboarding(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the user has a profile and an active goal.

    Drives the post-sign-in redirect: the design routes a new user into the
    wizard and a returning one straight to today.
    """
    # Imported here rather than at module scope: `Goal` and `UserProfile` belong
    # to the onboarding domain, and importing them at the top would make signing
    # in depend on it at import time.
    from app.db.models import Goal, UserProfile

    profile = await session.scalar(select(UserProfile.id).where(UserProfile.user_id == user_id))
    if profile is None:
        return False

    goal = await session.scalar(
        select(Goal.id).where(Goal.user_id == user_id, Goal.ends_on.is_(None))
    )
    return goal is not None
