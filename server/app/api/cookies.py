"""Auth cookie handling.

Both tokens travel as httpOnly cookies and are never exposed to JavaScript —
which is the point: a token readable by JS is a token stealable by any injected
script or compromised dependency.

The refresh cookie is additionally scoped to the auth router, so the one
credential that can mint access tokens is not attached to every API call the app
makes — only the two routes that actually read it ever see it.

A third, short-lived cookie carries the OAuth state and PKCE verifier between the
two legs of a redirect sign-in. Every cookie flag in this app lives in this one
file, which is what makes "the path used to clear it must match the path used to
set it" auditable rather than a rule each caller is trusted to remember.
"""

from fastapi import Request, Response

from app.config import settings


def set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.access_cookie_name,
        value=token,
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        # Narrower than the access cookie on purpose.
        path=settings.refresh_cookie_path,
    )


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    set_access_cookie(response, access_token)
    set_refresh_cookie(response, refresh_token)


def clear_auth_cookies(response: Response) -> None:
    # Paths must match the ones used to set them, or the browser keeps the
    # original cookie and "sign out" silently does nothing.
    response.delete_cookie(
        key=settings.access_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


# The state cookie is read by exactly one route, so it is scoped to exactly that
# path — narrower even than the refresh cookie. This must track the route's real
# path: a mismatch is silent, the browser simply never sends the cookie and every
# sign-in fails the state check with nothing naming the cause.
OAUTH_STATE_COOKIE_PATH = f"{settings.api_v1_prefix}/auth/google/callback"

# Bounds how long a half-finished authorization stays redeemable. Long enough for
# an account chooser, a password and a 2FA prompt; short enough that a cookie left
# behind in an abandoned tab is not a standing invitation.
OAUTH_STATE_TTL_SECONDS = 600


def set_oauth_state_cookie(response: Response, *, state: str, code_verifier: str) -> None:
    """Remember what this browser started, for the callback to check against."""
    response.set_cookie(
        key=settings.oauth_state_cookie_name,
        # One cookie, not two. The state and the verifier are a single fact —
        # that this browser began this authorization — and splitting them invents
        # a case where one arrives and the other does not. Neither half can
        # contain a dot: both come from `secrets.token_urlsafe`, whose alphabet
        # is base64url.
        value=f"{state}.{code_verifier}",
        max_age=OAUTH_STATE_TTL_SECONDS,
        # Never read by script. A readable state is one an injected script can
        # exfiltrate and pair with a code lifted from the address bar; a readable
        # verifier defeats PKCE outright.
        httponly=True,
        secure=settings.cookie_secure,
        # A literal "lax", and this is the one cookie in the app that must not
        # follow `settings.cookie_samesite`. Google returns the user here with a
        # cross-site top-level GET, which "lax" is defined by the spec to be sent
        # on and "strict" is defined not to be. Tightening the deployment-wide
        # setting would silently break every sign-in and nothing else.
        samesite="lax",
        path=OAUTH_STATE_COOKIE_PATH,
    )


def read_oauth_state_cookie(request: Request) -> tuple[str, str]:
    """The state and verifier this browser started with, or two empty strings."""
    raw = request.cookies.get(settings.oauth_state_cookie_name, "")
    state, _, code_verifier = raw.partition(".")
    return state, code_verifier


def clear_oauth_state_cookie(response: Response) -> None:
    # Single use. The state has done its whole job the moment the callback has
    # compared it, and leaving it live for the rest of its ten minutes would let
    # the same authorization leg be raced with a second code.
    response.delete_cookie(
        key=settings.oauth_state_cookie_name,
        path=OAUTH_STATE_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
