"""Auth cookie handling.

Both tokens travel as httpOnly cookies and are never exposed to JavaScript —
which is the point: a token readable by JS is a token stealable by any injected
script or compromised dependency.

The refresh cookie is additionally scoped to the auth router, so a 30-day
credential is not attached to every API call the app makes.
"""

from fastapi import Response

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
