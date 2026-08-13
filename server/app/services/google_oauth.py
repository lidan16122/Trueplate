"""Google ID-token verification.

``google-auth`` fetches and caches Google's signing certificates over a
*synchronous* HTTP transport. Calling it directly from an async endpoint would
block the event loop for the duration of that fetch — which, on a cold cache, is
a network round-trip that stalls every other in-flight request on the worker.
``run_in_threadpool`` keeps the request path non-blocking.
"""

import logging
from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from starlette.concurrency import run_in_threadpool

from app.config import settings

logger = logging.getLogger(__name__)

# Google mints tokens under both spellings and both are legitimate.
VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Reused across calls so the certificate cache is shared rather than refetched
# on every sign-in. Safe to share: it is a plain requests.Session wrapper.
_transport = google_requests.Request()


class GoogleAuthError(Exception):
    """The credential was not a valid Google ID token for this application."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    first_name: str
    last_name: str
    picture: str | None


def _verify_sync(credential: str) -> dict:
    # Passing the client id makes google-auth check `aud` for us; a token minted
    # for a different application is rejected rather than silently accepted.
    return id_token.verify_oauth2_token(credential, _transport, settings.google_client_id)


async def verify_google_credential(credential: str) -> GoogleIdentity:
    if not settings.google_client_id:
        raise GoogleAuthError("GOOGLE_CLIENT_ID is not configured on the server")

    try:
        payload = await run_in_threadpool(_verify_sync, credential)
    except ValueError as exc:
        # google-auth raises ValueError for every rejection: bad signature,
        # expired, wrong audience. The detail is useful in logs, never to the
        # caller — it would confirm which part of a forged token was wrong.
        logger.warning("Google credential rejected: %s", exc)
        raise GoogleAuthError("Google sign-in could not be verified") from exc

    if payload.get("iss") not in VALID_ISSUERS:
        raise GoogleAuthError("Unexpected token issuer")

    if not payload.get("email"):
        raise GoogleAuthError("Google account has no email address")

    if not payload.get("email_verified", False):
        # An unverified Google address could belong to someone else; treating it
        # as an identity would let an attacker claim a victim's account.
        raise GoogleAuthError("Google account email is not verified")

    return GoogleIdentity(
        subject=payload["sub"],
        email=payload["email"].lower(),
        email_verified=True,
        first_name=payload.get("given_name", ""),
        last_name=payload.get("family_name", ""),
        picture=payload.get("picture"),
    )
