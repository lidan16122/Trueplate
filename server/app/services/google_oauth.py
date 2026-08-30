"""Google sign-in: the authorization-code legs, and ID-token verification.

Two halves of one conversation, kept in one module because they are one protocol
with one client id. ``begin_authorization`` and ``exchange_code_for_id_token``
run the OAuth 2.0 authorization-code flow; ``verify_google_credential`` checks
whatever ID token comes out of it, and is the same function the older
``POST /auth/google`` path calls with a token the browser handed over.

``google-auth`` fetches and caches Google's signing certificates over a
*synchronous* HTTP transport. Calling it directly from an async endpoint would
block the event loop for the duration of that fetch — which, on a cold cache, is
a network round-trip that stalls every other in-flight request on the worker.
``run_in_threadpool`` keeps the request path non-blocking. The code exchange
below needs none of that: httpx is already async.
"""

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from starlette.concurrency import run_in_threadpool

from app.config import settings

logger = logging.getLogger(__name__)

# From the discovery document at
# https://accounts.google.com/.well-known/openid-configuration. Hardcoded rather
# than fetched: discovery would put a second network round-trip in front of every
# sign-in to learn two URLs that have not moved in a decade, and would turn a
# discovery outage into a sign-in outage.
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Exactly the claims `verify_google_credential` below reads, and nothing more:
# `openid` for the subject identities are matched on, `email` for the address and
# its verified flag, `profile` for the name and picture.
#
# `access_type` is deliberately absent from the authorization request. Its
# default is `online`; asking for `offline` would hand us a long-lived Google
# refresh token to store and protect, in exchange for a capability this app never
# uses — it calls no Google API.
SCOPES = "openid email profile"

# Google mints tokens under both spellings and both are legitimate.
VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Reused across calls so the certificate cache is shared rather than refetched
# on every sign-in. Safe to share: it is a plain requests.Session wrapper.
_transport = google_requests.Request()

# How far our clock may lag Google's before a token is treated as forged.
#
# ``google-auth`` defaults this to **zero**, which means a token whose `iat` is a
# single second ahead of this machine's clock is rejected outright — observed as
# "Token used too early, 1787428240 < 1787428241" and surfaced to the user as a
# failed sign-in. No clock agrees with Google's to the second, so a strict zero
# makes sign-in fail intermittently on a perfectly healthy deployment.
#
# It widens the expiry check by the same amount. That costs nothing worth
# worrying about: a Google ID token lives an hour and is exchanged for our own
# session cookies immediately, so thirty seconds of grace at the end of it is not
# a window anyone can use.
#
# This is tolerance, not a fix for a broken clock. A host drifting further than
# this needs its time service looked at — the failure will come back, and by then
# tokens will be *expiring* early too, which no skew allowance here can rescue.
CLOCK_SKEW_SECONDS = 30


class GoogleAuthError(Exception):
    """The credential was not a valid Google ID token for this application."""


class GoogleTokenExchangeError(Exception):
    """The authorization code could not be traded for an ID token."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    first_name: str
    last_name: str
    picture: str | None


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """A started sign-in: where to send the browser, and what to remember."""

    url: str
    state: str
    code_verifier: str


_client: httpx.AsyncClient | None = None


def get_google_http_client() -> httpx.AsyncClient:
    """The shared client for Google's token endpoint.

    Deliberately not ``services/nutrition/http.py``. That client belongs to the
    nutrition package and is sized and timed for food lookups, so sharing it
    would make a change to ``NUTRITION_TIMEOUT_SECONDS`` quietly retune sign-in.

    Lazy for the same reason as that one: importing this module must not open a
    socket, which is what lets the suite import the app with no network stack.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            # Every external client in this app carries a timeout. httpx's own
            # default is None, so a slow Google would pin a worker open and
            # present as this app being down.
            timeout=httpx.Timeout(settings.google_timeout_seconds),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


async def close_google_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def begin_authorization() -> AuthorizationRequest:
    """Mint a fresh state and PKCE pair, and build the URL to send the browser to.

    Lives here rather than in the route so the route never has to know what S256
    is; it only has to remember the two values it is handed.

    PKCE despite this being a confidential client with a secret, which the
    classic argument says makes it unnecessary. The reason is specific to this
    deployment: the authorization code comes back in a *query string* on the app
    origin and is then proxied through Cloudflare to Render, two extra hops that
    both log request URLs. A code recovered from a log is redeemable with the
    secret alone; with PKCE it is worthless without a verifier that only ever
    existed in an httpOnly cookie on the victim's own browser.
    """
    state = secrets.token_urlsafe(32)
    # 86 characters, comfortably inside RFC 7636's 43–128 and drawn from the
    # base64url alphabet it requires.
    code_verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Without this, a user with one live Google session is signed straight
        # back in with no chance to pick a different account — and there is no
        # other way out, because this app's own sign-out cannot reach Google's
        # session. Costs a returning user one click.
        "prompt": "select_account",
    }
    return AuthorizationRequest(
        url=f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}",
        state=state,
        code_verifier=code_verifier,
    )


async def exchange_code_for_id_token(*, code: str, code_verifier: str) -> str:
    """Trade the authorization code for the ID token behind it.

    Server-to-server over TLS, carrying the client secret, so the ID token never
    passes through the browser at all. That is the property the popup flow this
    replaces never had, and it is also why no ``nonce`` is needed: a nonce exists
    to stop a token minted for someone else being injected through the front
    channel, and here there is no front channel to inject one into.
    """
    if not settings.google_client_secret:
        raise GoogleTokenExchangeError("GOOGLE_CLIENT_SECRET is not configured on the server")

    try:
        response = await get_google_http_client().post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                # Google re-checks this against the one the authorization request
                # carried, which is why both legs read the same setting rather
                # than each building a URL that could drift from the other.
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
    except httpx.HTTPError as exc:
        raise GoogleTokenExchangeError(f"Token endpoint unreachable: {exc}") from exc

    if response.status_code != 200:
        # Status and Google's own error code only. The request body carried the
        # client secret, so anything richer risks a log line derived from it.
        raise GoogleTokenExchangeError(
            f"Token endpoint returned {response.status_code} ({_token_error_code(response)})"
        )

    try:
        id_token_value = response.json().get("id_token", "")
    except ValueError as exc:
        raise GoogleTokenExchangeError("Token response was not JSON") from exc

    if not id_token_value:
        # A 200 with no id_token means the `openid` scope did not survive the
        # request. Worth its own message: the fix is in what we sent, not in
        # anything the user did.
        raise GoogleTokenExchangeError("Token response carried no id_token")

    # The access token in the same payload is dropped on the floor on purpose.
    # Nothing here calls a Google API, and a credential we keep is a credential
    # we have to protect.
    return id_token_value


def _token_error_code(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", "no error code"))
    except ValueError:
        return "unparseable body"


def _verify_sync(credential: str) -> dict:
    # Passing the client id makes google-auth check `aud` for us; a token minted
    # for a different application is rejected rather than silently accepted.
    return id_token.verify_oauth2_token(
        credential,
        _transport,
        settings.google_client_id,
        clock_skew_in_seconds=CLOCK_SKEW_SECONDS,
    )


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
