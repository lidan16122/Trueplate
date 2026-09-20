"""Revocable device sessions with a stable, opaque refresh credential.

Only the credential's SHA-256 is stored. Renewal keeps the same credential so
concurrent tabs and lost responses cannot consume each other's session.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from redis.asyncio import Redis

from app.config import settings
from app.stores import keys

TOKEN_BYTES = 32  # 256 bits


def generate_refresh_token() -> str:
    """An opaque credential whose session can be revoked server-side."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# KEYS[1] token key; ARGV: family prefix, user prefix, ttl, now, token hash.
# Checking the family and extending its expiry together prevents renewal from
# recreating a session that logout has already removed.
_RENEW_LUA = """
local token = redis.call('HMGET', KEYS[1], 'user_id', 'family_id')
if not token[1] or not token[2] then return {'INVALID'} end

local user_id = token[1]
local family_id = token[2]
local family_key = ARGV[1] .. family_id
local user_key = ARGV[2] .. user_id
local family = redis.call('HMGET', family_key, 'user_id', 'current_token_hash')
if family[1] ~= user_id or family[2] ~= ARGV[5] then return {'INVALID'} end

local ttl = tonumber(ARGV[3])
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('HSET', family_key, 'last_used_at', ARGV[4])
redis.call('EXPIRE', family_key, ttl)
redis.call('SADD', user_key, family_id)
redis.call('EXPIRE', user_key, ttl)
return {'OK', user_id, family_id}
"""

# KEYS[1] family key; ARGV: token prefix, user prefix, optional owner id.
# Ownership is checked inside the mutation so a foreign family id is a no-op.
_REVOKE_FAMILY_LUA = """
local family = redis.call('HGETALL', KEYS[1])
if #family == 0 then return 0 end

local data = {}
for i = 1, #family, 2 do data[family[i]] = family[i + 1] end

local owner = ARGV[3]
if owner ~= '' and data['user_id'] ~= owner then return 0 end

if data['current_token_hash'] then
  redis.call('DEL', ARGV[1] .. data['current_token_hash'])
end
if data['user_id'] then
  redis.call('SREM', ARGV[2] .. data['user_id'], data['family_id'] or '')
end
redis.call('DEL', KEYS[1])
return 1
"""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    raw_token: str
    family_id: str


@dataclass(frozen=True, slots=True)
class RenewalResult:
    """Identity of a live session, or rejection without modifying other sessions."""

    status: Literal["ok", "invalid"]
    user_id: str | None = None
    family_id: str | None = None


class RefreshTokenStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._ttl = settings.refresh_token_ttl_seconds
        self._renew = redis.register_script(_RENEW_LUA)
        self._revoke_family_script = redis.register_script(_REVOKE_FAMILY_LUA)

    async def create_session(
        self,
        *,
        user_id: str,
        device_label: str = "Unknown device",
        user_agent: str = "",
        ip: str = "",
    ) -> IssuedToken:
        """Start a separate session per sign-in, keeping only its credential hash."""
        raw_token = generate_refresh_token()
        token_hash = hash_token(raw_token)
        family_id = str(uuid.uuid4())
        now = _now_iso()

        # Keep the existing key layout so deployed sessions survive this change.
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(
            keys.refresh_token_key(token_hash),
            mapping={"user_id": user_id, "family_id": family_id, "issued_at": now},
        )
        pipe.expire(keys.refresh_token_key(token_hash), self._ttl)
        pipe.hset(
            keys.refresh_family_key(family_id),
            mapping={
                "user_id": user_id,
                "family_id": family_id,
                "current_token_hash": token_hash,
                "device_label": device_label,
                "user_agent": user_agent[:512],
                "ip": ip,
                "created_at": now,
                "last_used_at": now,
            },
        )
        pipe.expire(keys.refresh_family_key(family_id), self._ttl)
        pipe.sadd(keys.refresh_user_families_key(user_id), family_id)
        pipe.expire(keys.refresh_user_families_key(user_id), self._ttl)
        await pipe.execute()

        return IssuedToken(raw_token=raw_token, family_id=family_id)

    async def renew(self, raw_token: str) -> RenewalResult:
        """Extend a live session without replacing its credential.

        Every caller receives the same outcome regardless of response ordering;
        an unknown, expired, or revoked credential cannot restore a session.
        """
        token_hash = hash_token(raw_token)
        result = await self._renew(
            keys=[keys.refresh_token_key(token_hash)],
            args=[
                keys.REFRESH_FAMILY_PREFIX,
                keys.REFRESH_USER_PREFIX,
                self._ttl,
                _now_iso(),
                token_hash,
            ],
        )
        if result[0] == "OK":
            return RenewalResult(status="ok", user_id=result[1], family_id=result[2])
        return RenewalResult(status="invalid")

    async def revoke_family(self, family_id: str, *, owner_id: str | None = None) -> bool:
        """Revoke a device session, restricted to its owner when supplied."""
        revoked = await self._revoke_family_script(
            keys=[keys.refresh_family_key(family_id)],
            args=[keys.REFRESH_TOKEN_PREFIX, keys.REFRESH_USER_PREFIX, owner_id or ""],
        )
        return bool(revoked)

    async def revoke_by_token(self, raw_token: str) -> bool:
        """Sign out of the current device, given its refresh credential."""
        token_hash = hash_token(raw_token)
        record = await self._redis.hgetall(keys.refresh_token_key(token_hash))
        if not record:
            return False
        return await self.revoke_family(record["family_id"])

    async def revoke_all_for_user(self, user_id: str) -> int:
        """Sign out everywhere. Not wired to a route yet; the store supports it."""
        family_ids = await self._redis.smembers(keys.refresh_user_families_key(user_id))
        revoked = 0
        for family_id in family_ids:
            if await self.revoke_family(family_id):
                revoked += 1
        await self._redis.delete(keys.refresh_user_families_key(user_id))
        return revoked
