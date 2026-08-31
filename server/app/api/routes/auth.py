import logging
from dataclasses import dataclass
from hmac import compare_digest

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import (
    clear_auth_cookies,
    clear_oauth_state_cookie,
    read_oauth_state_cookie,
    set_auth_cookies,
    set_oauth_state_cookie,
)
from app.config import settings
from app.core.deps import CurrentUser, DbSession, Denylist, RefreshTokens, TokenClaims
from app.core.devices import describe_device
from app.core.security import create_access_token
from app.db.models import User
from app.schemas.auth import (
    GoogleSignInRequest,
    MessageResponse,
    SessionResponse,
    UserOut,
)
from app.services.auth_service import (
    EmailAlreadyRegisteredError,
    has_completed_onboarding,
    upsert_google_user,
)
from app.services.google_oauth import (
    GoogleAuthError,
    GoogleTokenExchangeError,
    begin_authorization,
    exchange_code_for_id_token,
    verify_google_credential,
)
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


@dataclass(frozen=True, slots=True)
class _EstablishedSession:
    """Everything a caller needs, in whichever shape it answers in."""

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


def _signin_redirect(reason: str = "") -> RedirectResponse:
    """Send the browser back to sign-in, carrying why in the query string.

    Every failure on the redirect legs answers this way rather than raising.
    ``raise HTTPException`` would render ``{"detail": ...}`` as a bare page in the
    user's own window — this is a top-level navigation, not an API call — and
    CLAUDE.md already forbids raising where a response carries cookies.

    303, not ``RedirectResponse``'s default of 307. 307 preserves the method,
    which is never what a redirect out of an auth leg wants.

    Relative, never absolute. A relative Location is resolved by the *browser*
    against the origin it is on, which is the app's; anything built here would be
    built from a Host header that both proxies in front of this app have already
    rewritten to the API's.

    The vocabulary of reasons is small and closed, and
    ``client/src/pages/SignIn.tsx`` maps it to sentences rather than rendering it:
    state | google | exchange | verification | email_in_use | unavailable, plus
    the empty string for a user who simply pressed Cancel.
    """
    return RedirectResponse(
        url=f"/signin?error={reason}" if reason else "/signin",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/google/start")
async def start_google_sign_in() -> RedirectResponse:
    """Begin the OAuth 2.0 authorization-code flow.

    A plain top-level GET navigation, which is the whole point. The popup this
    replaces could be refused by the browser with nothing in script able to ask
    for it back. The GSI redirect variant tried instead needs its CSRF cookie to
    survive a cross-site *POST* — precisely the case SameSite=Lax does not cover,
    rescued only by Chrome's two-minute Lax-allowing-unsafe intervention, which
    other browsers do not implement. Google returns the user from here with a
    cross-site top-level *GET*, and Lax is defined to be sent on exactly that, in
    every browser, with no clock running.
    """
    if not (
        settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri
    ):
        # Which of our own variables is missing goes in the log, never in the
        # redirect. Same rule as the 401 on POST /google: our misconfiguration is
        # ours to read, not something to hand to an unauthenticated caller.
        logger.error(
            "Google sign-in is not configured (client_id=%s secret=%s redirect_uri=%s)",
            bool(settings.google_client_id),
            bool(settings.google_client_secret),
            bool(settings.google_redirect_uri),
        )
        return _signin_redirect("unavailable")

    authorization = begin_authorization()
    response = RedirectResponse(url=authorization.url, status_code=status.HTTP_303_SEE_OTHER)
    set_oauth_state_cookie(
        response, state=authorization.state, code_verifier=authorization.code_verifier
    )
    return response


def _abandon_sign_in(reason: str = "") -> RedirectResponse:
    """Give up on a redirect sign-in, taking the state cookie with it.

    Every exit from the callback drops the cookie, failures included. Either it
    is stale — in which case keeping it is useless — or it never arrived, in
    which case clearing it is a no-op. There is no case where holding it helps.
    """
    response = _signin_redirect(reason)
    clear_oauth_state_cookie(response)
    return response


@router.get("/google/callback")
async def complete_google_sign_in(
    request: Request,
    db: DbSession,
    refresh_tokens: RefreshTokens,
    # All three default rather than being required. A missing required query
    # param raises a 422 *before the body runs*, and FastAPI renders that as JSON
    # in the user's own window — the exact failure this route is shaped to avoid.
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Google's landing point, carrying an authorization code.

    The code is traded for the ID token server-to-server, so the token never
    passes through the browser at all.
    """
    expected_state, code_verifier = read_oauth_state_cookie(request)

    if error:
        # `access_denied` is a user pressing Cancel. Returning them to a clean
        # sign-in screen is the honest answer; an error note would accuse the app
        # of failing at something the user chose not to do.
        logger.info("Google returned an authorization error: %s", error)
        return _abandon_sign_in("" if error == "access_denied" else "google")

    # Empty values are rejected before the comparison, because `compare_digest`
    # of two empty byte strings is True — stripping the cookie would otherwise be
    # a way to *pass* this check rather than fail it.
    #
    # And compared as bytes, not as str: `compare_digest` raises TypeError on a
    # str holding any non-ASCII character, and `state` here is whatever the URL
    # said. Comparing as str turns one chosen character into an uncaught 500 —
    # the bare error page in the user's own window that this route exists to
    # avoid, with the route falsifying its own "never raises" property.
    if (
        not expected_state
        or not code_verifier
        or not state
        or not compare_digest(expected_state.encode(), state.encode())
    ):
        logger.warning("Google callback rejected: state cookie missing or mismatched")
        return _abandon_sign_in("state")

    if not code:
        logger.warning("Google callback carried neither a code nor an error")
        return _abandon_sign_in("google")

    try:
        id_token_value = await exchange_code_for_id_token(code=code, code_verifier=code_verifier)
    except GoogleTokenExchangeError as exc:
        logger.warning("Google token exchange failed: %s", exc)
        return _abandon_sign_in("exchange")

    try:
        session = await _establish_session(db, refresh_tokens, request, id_token_value)
    except GoogleAuthError as exc:
        logger.warning("Google credential rejected: %s", exc)
        return _abandon_sign_in("verification")
    except EmailAlreadyRegisteredError:
        return _abandon_sign_in("email_in_use")
    except Exception:
        # A broad catch, which is right here and nowhere else in this app.
        # Postgres and the refresh-token store are both reachable from
        # `_establish_session`, and an exception escaping this route is not a 500
        # some API client parses — it is a bare error page in the user's own
        # window, which is the single thing this route promises never to produce.
        # Without this the promise is false for every failure we did not name.
        #
        # `logger.exception` rather than a message: unlike every other branch
        # here, we do not know what happened, so the traceback is the only record.
        logger.exception("Google callback failed unexpectedly")
        return _abandon_sign_in("unavailable")

    # `/onboarding` only when the server actually computed it: ProtectedRoute
    # bounces a user who needs onboarding away from /today, but does *not* bounce
    # one who does not need it away from /onboarding — guessing wrong in that
    # direction strands them in the wizard with no way forward.
    #
    # These paths belong to client/src/router.tsx and nothing mechanical ties the
    # two together. The tests asserting the literal strings are the only thing
    # that would notice a rename.
    destination = "/onboarding" if session.needs_onboarding else "/today"
    response = RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(
        response, access_token=session.access_token, refresh_token=session.refresh_token
    )
    clear_oauth_state_cookie(response)
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
