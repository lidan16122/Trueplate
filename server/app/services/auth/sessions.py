"""Session creation shared by JSON sign-in and the OAuth redirect."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import AccessTokenClaims, create_access_token
from app.db.models import User
from app.services.auth.google_oauth import verify_google_credential
from app.services.auth.identity import has_completed_onboarding, upsert_google_user
from app.services.errors import NotFoundError
from app.stores.access_tokens import AccessTokenDenylist
from app.stores.refresh_tokens import RefreshTokenStore, RotationResult
from app.utils.devices import describe_device


@dataclass(frozen=True, slots=True)
class EstablishedSession:
    """Everything a caller needs, in whichever shape it answers in."""

    user: User
    access_token: str
    refresh_token: str
    needs_onboarding: bool


async def establish_session(
    db: AsyncSession,
    refresh_tokens: RefreshTokenStore,
    credential: str,
    *,
    user_agent: str,
    ip: str,
) -> EstablishedSession:
    """Turn a Google ID token into a session, minus the response.

    Shared by the two ways a credential reaches us: a browser posting it as JSON,
    and our own token exchange returning one after a redirect. Everything between
    the credential and the response is identical for both; only the shape of the
    answer differs, so the response is deliberately not built here — the caller
    decides whether the cookies hang off a JSON body or a redirect.

    Raises ``GoogleAuthError`` and ``EmailAlreadyRegisteredError`` rather than
    translating them, because the right *kind* of response differs per caller
    too: a 401 body is correct for an API client, and would be rendered as bare
    JSON in the user's own window for a redirect.
    """
    identity = await verify_google_credential(credential)
    resolved = await upsert_google_user(db, identity)

    issued = await refresh_tokens.create_session(
        user_id=str(resolved.user.id),
        device_label=describe_device(user_agent),
        user_agent=user_agent,
        ip=ip,
    )
    access = create_access_token(user_id=str(resolved.user.id), session_id=issued.family_id)

    needs_onboarding = resolved.is_new_user or not await has_completed_onboarding(
        db, resolved.user.id
    )
    return EstablishedSession(
        user=resolved.user,
        access_token=access.token,
        refresh_token=issued.raw_token,
        needs_onboarding=needs_onboarding,
    )


async def rotate_session(
    refresh_tokens: RefreshTokenStore, raw_token: str
) -> tuple[RotationResult, str | None]:
    """Mint an access token only after the store has accepted the rotation."""
    result = await refresh_tokens.rotate(raw_token)
    access_token = None
    if result.status == "ok":
        access = create_access_token(user_id=result.user_id, session_id=result.family_id)
        access_token = access.token
    return result, access_token


async def revoke_session(
    refresh_tokens: RefreshTokenStore,
    denylist: AccessTokenDenylist,
    family_id: str,
    user_id: str,
    claims: AccessTokenClaims,
) -> bool:
    """Revoke an owned family and report whether the caller's cookies must go too."""
    # Ownership is part of the atomic revoke, so there is no gap between a
    # separate ownership check and the mutation.
    revoked = await refresh_tokens.revoke_family(family_id, owner_id=user_id)
    if not revoked:
        raise NotFoundError("Session not found")

    if family_id == claims.session_id:
        # Preserve immediate access-token revocation when configured; otherwise
        # this device's cookie would keep working until its normal expiry.
        await denylist.revoke(claims.jti, ttl_seconds=settings.access_token_ttl_seconds)

    return family_id == claims.session_id
