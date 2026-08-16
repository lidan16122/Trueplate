import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.cookies import clear_auth_cookies, set_auth_cookies
from app.config import settings
from app.core.deps import CurrentUser, DbSession, Denylist, RefreshTokens, TokenClaims
from app.core.devices import describe_device
from app.core.security import create_access_token
from app.schemas.auth import (
    GoogleSignInRequest,
    MessageResponse,
    SessionListResponse,
    SessionOut,
    SignInResponse,
    UserOut,
)
from app.services.auth_service import (
    EmailAlreadyRegisteredError,
    has_completed_onboarding,
    upsert_google_user,
)
from app.services.google_oauth import GoogleAuthError, verify_google_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is client-controlled unless a trusted proxy overwrites it;
    # treated as a display hint only, never as an authorisation input.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/google", response_model=SignInResponse)
async def sign_in_with_google(
    payload: GoogleSignInRequest,
    request: Request,
    response: Response,
    db: DbSession,
    refresh_tokens: RefreshTokens,
) -> SignInResponse:
    """Exchange a Google ID token for a session."""
    try:
        identity = await verify_google_credential(payload.credential)
    except GoogleAuthError as exc:
        # One fixed message. `str(exc)` distinguishes "unexpected issuer" from
        # "email is not verified" from "GOOGLE_CLIENT_ID is not configured on
        # the server" — the first two tell a caller how their forgery failed,
        # and the third reports our own misconfiguration through a 401.
        logger.warning("Google credential rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google sign-in could not be verified",
        ) from exc

    try:
        resolved = await upsert_google_user(db, identity)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered with a different sign-in method",
        ) from exc
    user_agent = request.headers.get("user-agent", "")

    issued = await refresh_tokens.create_session(
        user_id=str(resolved.user.id),
        device_label=describe_device(user_agent),
        user_agent=user_agent,
        ip=_client_ip(request),
    )
    access = create_access_token(user_id=str(resolved.user.id), session_id=issued.family_id)
    set_auth_cookies(response, access_token=access.token, refresh_token=issued.raw_token)

    needs_onboarding = resolved.is_new_user or not await has_completed_onboarding(
        db, resolved.user.id
    )

    return SignInResponse(
        user=UserOut.model_validate(resolved.user),
        needs_onboarding=needs_onboarding,
    )


def _expired_session_response(detail: str) -> JSONResponse:
    """A 401 that also tears down the cookies.

    Built explicitly rather than raised as an HTTPException: FastAPI discards
    the injected ``Response`` when an exception propagates, so cookies cleared
    on it never reach the browser. That would leave the client replaying a
    revoked token forever.
    """
    response = JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": detail})
    clear_auth_cookies(response)
    return response


@router.post("/refresh", response_model=MessageResponse)
async def refresh_session(
    request: Request,
    response: Response,
    refresh_tokens: RefreshTokens,
):
    """Rotate the refresh token and mint a fresh access token.

    Every terminal failure clears the cookies, so a client that has lost its
    session cannot sit in a refresh loop against a dead token.
    """
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        return _expired_session_response("No refresh token")

    result = await refresh_tokens.rotate(raw_token)

    if result.status == "ok":
        access = create_access_token(user_id=result.user_id, session_id=result.family_id)
        set_auth_cookies(response, access_token=access.token, refresh_token=result.raw_token)
        return MessageResponse(detail="Session refreshed")

    if result.status == "retry":
        # A concurrent refresh already won. The session is fine and the winner's
        # cookie is live, so 409 rather than 401 — and crucially the cookies are
        # left alone. The client should retry the original request, not tear
        # down and send the user to sign-in.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A concurrent refresh is in progress; retry the request",
        )

    if result.status == "reuse_detected":
        logger.warning("Refresh token reuse detected; revoked session family %s", result.family_id)
        return _expired_session_response("Session revoked. Please sign in again.")

    return _expired_session_response("Refresh token is invalid or expired")


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    refresh_tokens: RefreshTokens,
) -> MessageResponse:
    """Sign out of this device.

    Unauthenticated on purpose: signing out must work even when the access token
    has already expired, and it can only ever destroy the caller's own session.
    """
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        await refresh_tokens.revoke_by_token(raw_token)

    clear_auth_cookies(response)
    return MessageResponse(detail="Signed out")


@router.get("/me", response_model=UserOut)
async def read_current_user(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    user: CurrentUser, claims: TokenClaims, refresh_tokens: RefreshTokens
) -> SessionListResponse:
    """Devices this account is currently signed in on."""
    sessions = await refresh_tokens.list_sessions(str(user.id))
    return SessionListResponse(
        sessions=[
            SessionOut(
                family_id=s.family_id,
                device_label=s.device_label,
                ip=s.ip,
                created_at=s.created_at,
                last_used_at=s.last_used_at,
                is_current=s.family_id == claims.session_id,
            )
            for s in sessions
        ]
    )


@router.delete("/sessions/{family_id}", response_model=MessageResponse)
async def revoke_session(
    family_id: str,
    user: CurrentUser,
    claims: TokenClaims,
    response: Response,
    refresh_tokens: RefreshTokens,
    denylist: Denylist,
) -> MessageResponse:
    """Sign a specific device out."""
    # Ownership is part of the revoke itself, not a check in front of it: the
    # script compares the family's `user_id` before touching anything, so a
    # family belonging to someone else is a no-op by construction. A separate
    # check here would leave a window between the check and the revoke, and
    # would be a check someone could later forget.
    revoked = await refresh_tokens.revoke_family(family_id, owner_id=str(user.id))
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if family_id == claims.session_id:
        # Revoking the session you are currently using: deny the access token
        # too. Otherwise "sign this device out" leaves the token in the caller's
        # own cookie working for up to another 15 minutes. A no-op unless
        # instant revocation is switched on.
        await denylist.revoke(claims.jti, ttl_seconds=settings.access_token_ttl_seconds)

    if family_id == claims.session_id:
        clear_auth_cookies(response)

    return MessageResponse(detail="Session revoked")
