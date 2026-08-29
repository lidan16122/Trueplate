import logging
from dataclasses import dataclass
from hmac import compare_digest
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import clear_auth_cookies, set_auth_cookies
from app.config import settings
from app.core.deps import CurrentUser, DbSession, Denylist, RefreshTokens, TokenClaims
from app.core.devices import describe_device
from app.core.security import create_access_token
from app.db.models import User
from app.schemas.auth import (
    GoogleSignInRequest,
    MessageResponse,
    SessionListResponse,
    SessionOut,
    SessionResponse,
    UserOut,
)
from app.services.auth_service import (
    EmailAlreadyRegisteredError,
    has_completed_onboarding,
    upsert_google_user,
)
from app.services.google_oauth import GoogleAuthError, verify_google_credential
from app.stores.refresh_tokens import RefreshTokenStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is client-controlled unless a trusted proxy overwrites it;
    # treated as a display hint only, never as an authorisation input.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@dataclass(frozen=True)
class _EstablishedSession:
    """Everything a caller needs to answer, in whichever shape it answers in."""

    user: User
    access_token: str
    refresh_token: str
    needs_onboarding: bool


async def _establish_session(
    db: AsyncSession,
    refresh_tokens: RefreshTokenStore,
    request: Request,
    credential: str,
) -> _EstablishedSession:
    """Turn a Google ID token into a session, minus the response.

    Shared by the two ways a credential reaches us: the browser posting it as
    JSON, and Google posting it as a form after a redirect. Everything between
    the credential and the response is identical for both; only the shape of the
    answer differs, so the response is deliberately not built here — the caller
    decides whether cookies hang off a JSON body or a redirect.

    Raises ``GoogleAuthError`` and ``EmailAlreadyRegisteredError`` rather than
    translating them, because the right status and the right *kind* of response
    differ per caller too: a 401 body is correct for an API client and would be
    rendered as bare JSON in the user's window for a redirect.
    """
    identity = await verify_google_credential(credential)
    resolved = await upsert_google_user(db, identity)

    user_agent = request.headers.get("user-agent", "")
    issued = await refresh_tokens.create_session(
        user_id=str(resolved.user.id),
        device_label=describe_device(user_agent),
        user_agent=user_agent,
        ip=_client_ip(request),
    )
    access = create_access_token(user_id=str(resolved.user.id), session_id=issued.family_id)

    needs_onboarding = resolved.is_new_user or not await has_completed_onboarding(
        db, resolved.user.id
    )
    return _EstablishedSession(
        user=resolved.user,
        access_token=access.token,
        refresh_token=issued.raw_token,
        needs_onboarding=needs_onboarding,
    )


@router.post("/google", response_model=SessionResponse)
async def sign_in_with_google(
    payload: GoogleSignInRequest,
    request: Request,
    response: Response,
    db: DbSession,
    refresh_tokens: RefreshTokens,
) -> SessionResponse:
    """Exchange a Google ID token for a session."""
    try:
        session = await _establish_session(db, refresh_tokens, request, payload.credential)
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
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered with a different sign-in method",
        ) from exc

    set_auth_cookies(
        response, access_token=session.access_token, refresh_token=session.refresh_token
    )
    return SessionResponse(
        user=UserOut.model_validate(session.user),
        needs_onboarding=session.needs_onboarding,
    )


def _signin_redirect(reason: str) -> RedirectResponse:
    """Send the browser back to sign-in, carrying why in the query string.

    Every failure on the redirect route answers this way rather than raising.
    `raise HTTPException` would render ``{"detail": ...}`` as a bare page in the
    user's own window — this is a top-level navigation, not an API call — and
    CLAUDE.md already forbids raising where a response carries cookies.

    Nothing reads ``?error=`` on the client yet, so today this only reaches the
    server log. It is in the URL so the reason survives to the one place a user
    can copy from when reporting a failure.
    """
    return RedirectResponse(url=f"/signin?error={reason}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/google/callback")
async def google_redirect_callback(
    request: Request,
    db: DbSession,
    refresh_tokens: RefreshTokens,
    # Both default rather than being required, so a malformed post is answered
    # with a redirect too. A missing required Form field raises a 422 before the
    # body runs, and FastAPI would render that as JSON in the browser window.
    credential: Annotated[str, Form()] = "",
    g_csrf_token: Annotated[str, Form()] = "",
) -> Response:
    """Google's landing point for `ux_mode: "redirect"`.

    Google posts the credential here as a form after a full-page navigation,
    rather than handing it to JavaScript in a popup. That is the whole reason
    this exists: a popup can be refused by the browser with no recourse — no
    permission to request, no prompt to trigger — and a navigation cannot.

    The credential arrives on a *cross-site* POST, so it needs a CSRF check that
    a same-site cookie cannot provide. Google's double-submit is the mechanism:
    the same token in a cookie it set on this origin and in the form body, which
    a third-party page can forge in the body but cannot read or set as a cookie.
    """
    cookie_token = request.cookies.get("g_csrf_token", "")
    if not cookie_token or not g_csrf_token or not compare_digest(cookie_token, g_csrf_token):
        # Also covers the cookie simply not arriving. It is set by Google's
        # script on this origin and the POST that should carry it is cross-site,
        # which is exactly the case SameSite governs — so treat absence as a
        # failure to verify rather than as permission to skip verifying.
        logger.warning("Google redirect rejected: csrf token missing or mismatched")
        return _signin_redirect("csrf")

    if not credential:
        logger.warning("Google redirect rejected: no credential in the form body")
        return _signin_redirect("no_credential")

    try:
        session = await _establish_session(db, refresh_tokens, request, credential)
    except GoogleAuthError as exc:
        logger.warning("Google credential rejected: %s", exc)
        return _signin_redirect("verification")
    except EmailAlreadyRegisteredError:
        return _signin_redirect("email_in_use")

    # 303, not the RedirectResponse default of 307. 307 preserves the method, so
    # the browser would re-POST this form at the app route and land on a 404.
    # 303 is the one that turns a POST into the GET this needs.
    #
    # `/onboarding` only when the server actually computed it: ProtectedRoute
    # bounces a user who needs onboarding away from /today, but does *not* bounce
    # one who does not need it away from /onboarding — sending them there would
    # strand them in the wizard.
    destination = "/onboarding" if session.needs_onboarding else "/today"
    response = RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(
        response, access_token=session.access_token, refresh_token=session.refresh_token
    )
    return response


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


@router.get("/me", response_model=SessionResponse)
async def read_current_user(user: CurrentUser, db: DbSession) -> SessionResponse:
    """The session as the client sees it on a cold page load.

    Carries `needs_onboarding` and not just the user: the auth cookies are
    httpOnly, so a reload has no way to rediscover that the wizard is still
    outstanding. Without it the client can only learn this at sign-in, and a
    user who closed the tab mid-wizard comes back to a day view with no targets.
    """
    return SessionResponse(
        user=UserOut.model_validate(user),
        needs_onboarding=not await has_completed_onboarding(db, user.id),
    )


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
