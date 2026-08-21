"""Shared FastAPI dependencies."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import AccessTokenClaims, TokenError, decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.services.detection import DetectionService
from app.services.nutrition import (
    NutritionResolver,
    OpenFoodFactsClient,
    UsdaClient,
    get_http_client,
)
from app.stores.access_tokens import AccessTokenDenylist
from app.stores.client import get_redis
from app.stores.rate_limit import RateLimiter
from app.stores.refresh_tokens import RefreshTokenStore

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]

def unauthenticated() -> HTTPException:
    """A fresh 401 per call.

    A module-level instance would be one mutable object shared by every request
    on the worker: anything that touched its `headers` would leak the change
    into unrelated responses.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def get_refresh_token_store(redis: RedisClient) -> RefreshTokenStore:
    return RefreshTokenStore(redis)


def get_rate_limiter(redis: RedisClient) -> RateLimiter:
    return RateLimiter(redis)


def get_access_denylist(redis: RedisClient) -> AccessTokenDenylist:
    return AccessTokenDenylist(redis)


RefreshTokens = Annotated[RefreshTokenStore, Depends(get_refresh_token_store)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
Denylist = Annotated[AccessTokenDenylist, Depends(get_access_denylist)]


def get_nutrition_resolver(db: DbSession) -> NutritionResolver:
    # The HTTP client is process-wide and pooled; only the DB session is
    # per-request, which is why the resolver is built here rather than shared.
    http = get_http_client()
    return NutritionResolver(db, UsdaClient(http), OpenFoodFactsClient(http))


Resolver = Annotated[NutritionResolver, Depends(get_nutrition_resolver)]


def get_detection_service(resolver: Resolver) -> DetectionService:
    return DetectionService(resolver)


Detector = Annotated[DetectionService, Depends(get_detection_service)]


async def get_token_claims(request: Request, denylist: Denylist) -> AccessTokenClaims:
    """Verify the access-token cookie.

    Signature-only by default — no datastore round-trip. The denylist lookup
    happens solely when instant revocation is switched on.
    """
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        raise unauthenticated()

    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise unauthenticated() from exc

    if await denylist.is_revoked(claims.jti):
        raise unauthenticated()

    return claims


TokenClaims = Annotated[AccessTokenClaims, Depends(get_token_claims)]


async def get_current_user(claims: TokenClaims, db: DbSession) -> User:
    try:
        user_id = uuid.UUID(claims.user_id)
    except ValueError as exc:
        raise unauthenticated() from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        # A token outliving its user (deleted or deactivated mid-session) must
        # not keep working just because the signature is still good.
        raise unauthenticated()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
