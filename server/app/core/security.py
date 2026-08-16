"""Access-token minting and verification.

The access token is a short-lived, stateless JWT: verified by signature alone,
with no datastore round-trip on the hot path. That is the whole reason it is
separate from the refresh token — the refresh token is opaque and stateful so it
can be revoked, and the access token is stateless so the common case is fast.

The trade is that a revoked access token stays valid until it expires. Fifteen
minutes bounds that, and ``AccessTokenDenylist`` closes it entirely when the
deployment wants to pay for the lookup.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings

ACCESS_TOKEN_TYPE = "access"


class TokenError(Exception):
    """Token was missing, malformed, expired, or not one of ours."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: str
    session_id: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MintedAccessToken:
    token: str
    jti: str
    expires_at: datetime


def create_access_token(*, user_id: str, session_id: str) -> MintedAccessToken:
    """Mint an access token bound to a refresh-token family.

    ``sid`` carries the family id so a token can be traced back to the device it
    was issued for — which is what makes per-device revocation meaningful.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    jti = str(uuid.uuid4())

    token = jwt.encode(
        {
            "sub": user_id,
            "sid": session_id,
            "jti": jti,
            "typ": ACCESS_TOKEN_TYPE,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return MintedAccessToken(token=token, jti=jti, expires_at=expires_at)


def decode_access_token(token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            # Pinned to the configured algorithm. Accepting a list the attacker
            # can influence is how "alg: none" and HS/RS confusion attacks work.
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Access token is invalid") from exc

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        # Stops a token minted for another purpose being replayed as an access
        # token, should other token types ever share this secret.
        raise TokenError("Wrong token type")

    return AccessTokenClaims(
        user_id=payload["sub"],
        session_id=payload.get("sid", ""),
        jti=payload["jti"],
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
