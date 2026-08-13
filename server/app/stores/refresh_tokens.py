"""Refresh-token storage: rotation, theft detection, and per-device sessions.

Design notes worth keeping in mind before editing this file:

* The raw token never reaches Redis — only its SHA-256. A leaked database dump
  therefore yields nothing usable. SHA-256 rather than Argon2 is correct here:
  the input is 256 bits of ``secrets`` output, so there is no dictionary to
  attack and a slow KDF would only tax every refresh.

* Rotation is **one-time-use**. Presenting a token that was already rotated is
  not a mistake a healthy client makes — it means the token was captured — so
  it revokes the whole family rather than just that token.

* Rotation runs as a Lua script so check-and-swap is atomic. Without that, two
  refreshes racing from the same device both observe the token as active, and
  the loser is treated as a thief: the user gets signed out for using the app
  from two tabs. The client's single-flight refresh is the other half of this
  fix; neither alone is sufficient.
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
    """An opaque random string — deliberately not a JWT.

    A refresh token needs to be revocable, and a self-describing signed token is
    valid until it expires no matter what the server thinks.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# KEYS[1] rt:tok:<old>   KEYS[2] rt:used:<old>   KEYS[3] rt:tok:<new>
# ARGV[1] family prefix  ARGV[2] user prefix     ARGV[3] ttl
# ARGV[4] now (iso)      ARGV[5] new token hash
# ARGV[6] now (epoch)    ARGV[7] reuse grace seconds
#
# Returns {status, ...}:
#   {"OK", user_id, family_id} | {"RETRY", family_id}
#   | {"REUSE", family_id}     | {"INVALID"}
#
# Note: the family and user keys are derived inside the script from the value
# read out of KEYS[1], so they are not declared up front. That is safe on a
# single Redis node; moving to Redis Cluster would need hash tags to keep a
# family's keys in one slot.
_ROTATE_LUA = """
local active = redis.call('HGETALL', KEYS[1])

if #active == 0 then
  local used = redis.call('HGETALL', KEYS[2])
  if #used > 0 then
    local u = {}
    for i = 1, #used, 2 do u[used[i]] = used[i + 1] end

    -- Distinguish a concurrent retry from an actual replay. Two tabs (or one
    -- flaky connection) refreshing at the same instant would otherwise look
    -- identical to a stolen token, and revoking on that would sign real users
    -- out for opening a second tab.
    local age = tonumber(ARGV[6]) - tonumber(u['rotated_at'])
    if age <= tonumber(ARGV[7]) then
      return {'RETRY', u['family_id']}
    end
    return {'REUSE', u['family_id']}
  end
  -- Unknown or expired. Revoke nothing: a random string must not be able to
  -- destroy a session it has no relationship to.
  return {'INVALID'}
end

local data = {}
for i = 1, #active, 2 do data[active[i]] = active[i + 1] end

local user_id    = data['user_id']
local family_id  = data['family_id']
local family_key = ARGV[1] .. family_id
local user_key   = ARGV[2] .. user_id
local ttl        = tonumber(ARGV[3])
local now        = ARGV[4]
local new_hash   = ARGV[5]

redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[2], 'family_id', family_id, 'rotated_at', ARGV[6])
redis.call('EXPIRE', KEYS[2], ttl)

redis.call('HSET', KEYS[3], 'user_id', user_id, 'family_id', family_id, 'issued_at', now)
redis.call('EXPIRE', KEYS[3], ttl)

-- Only touch a family that still exists. A concurrent `revoke_family` (a
-- logout, or theft detection) may have deleted it between the HGETALL above
-- and here; an unconditional HSET would recreate it holding nothing but a
-- token hash, with no user_id for revoke to key off. The session would then
-- survive its own logout and be unreachable from the session list.
if redis.call('EXISTS', family_key) == 1 then
  -- Sliding expiration: an actively used session is never forced to re-login,
  -- while a genuinely dormant one still ages out.
  redis.call('HSET', family_key, 'current_token_hash', new_hash, 'last_used_at', now)
  redis.call('EXPIRE', family_key, ttl)
  redis.call('SADD', user_key, family_id)
  redis.call('EXPIRE', user_key, ttl)
else
  -- The family went away mid-rotation. Undo the token we just minted and
  -- report the session as gone, rather than leaving an orphan that resolves
  -- to a family nobody owns.
  redis.call('DEL', KEYS[3])
  return {'INVALID'}
end

return {'OK', user_id, family_id}
"""

# KEYS[1] rt:family:<id>
# ARGV[1] token prefix   ARGV[2] user prefix
_REVOKE_FAMILY_LUA = """
local family = redis.call('HGETALL', KEYS[1])
if #family == 0 then
  return 0
end

local data = {}
for i = 1, #family, 2 do data[family[i]] = family[i + 1] end

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
class RotationResult:
    """Outcome of consuming a refresh token.

    ``retry`` and ``reuse_detected`` are both replays of an already-rotated
    token, separated only by how long ago the rotation happened. The distinction
    matters enormously: one is a second browser tab, the other is a thief.
    """

    status: Literal["ok", "retry", "reuse_detected", "invalid"]
    user_id: str | None = None
    family_id: str | None = None
    raw_token: str | None = None


@dataclass(frozen=True, slots=True)
class SessionInfo:
    family_id: str
    device_label: str
    user_agent: str
    ip: str
    created_at: str
    last_used_at: str


class RefreshTokenStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._ttl = settings.refresh_token_ttl_seconds
        self._rotate = redis.register_script(_ROTATE_LUA)
        self._revoke_family_script = redis.register_script(_REVOKE_FAMILY_LUA)

    # ---------- issue ----------

    async def create_session(
        self,
        *,
        user_id: str,
        device_label: str = "Unknown device",
        user_agent: str = "",
        ip: str = "",
    ) -> IssuedToken:
        """Start a new token family — one per device/sign-in."""
        raw_token = generate_refresh_token()
        token_hash = hash_token(raw_token)
        family_id = str(uuid.uuid4())
        now = _now_iso()

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
                # Metadata exists so a "your active devices" screen can be built
                # without a schema change — see list_sessions.
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

    # ---------- rotate ----------

    async def rotate(self, raw_token: str) -> RotationResult:
        """Consume a refresh token and issue its replacement.

        On genuine reuse the whole family is revoked before returning, so the
        caller only has to translate the result into a response.
        """
        old_hash = hash_token(raw_token)
        new_raw = generate_refresh_token()
        new_hash = hash_token(new_raw)
        now = datetime.now(UTC)

        result = await self._rotate(
            keys=[
                keys.refresh_token_key(old_hash),
                keys.refresh_used_key(old_hash),
                keys.refresh_token_key(new_hash),
            ],
            args=[
                keys.REFRESH_FAMILY_PREFIX,
                keys.REFRESH_USER_PREFIX,
                self._ttl,
                now.isoformat(),
                new_hash,
                now.timestamp(),
                settings.refresh_reuse_grace_seconds,
            ],
        )

        status = result[0]
        if status == "OK":
            return RotationResult(
                status="ok", user_id=result[1], family_id=result[2], raw_token=new_raw
            )

        if status == "RETRY":
            # A concurrent refresh already won. Reject this one, but leave the
            # session intact — the winner's token is the live one.
            return RotationResult(status="retry", family_id=result[1])

        if status == "REUSE":
            family_id = result[1]
            await self.revoke_family(family_id)
            return RotationResult(status="reuse_detected", family_id=family_id)

        return RotationResult(status="invalid")

    # ---------- revoke ----------

    async def revoke_family(self, family_id: str) -> bool:
        """Kill one device/session. Also the theft response."""
        revoked = await self._revoke_family_script(
            keys=[keys.refresh_family_key(family_id)],
            args=[keys.REFRESH_TOKEN_PREFIX, keys.REFRESH_USER_PREFIX],
        )
        return bool(revoked)

    async def revoke_by_token(self, raw_token: str) -> bool:
        """Sign out of the current device, given its refresh token."""
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

    # ---------- inspect ----------

    async def list_sessions(self, user_id: str) -> list[SessionInfo]:
        """Active devices for a user, newest first.

        Families expire on their own TTL while the user's set does not shrink
        with them, so dead ids are pruned lazily here rather than by a sweeper.
        """
        user_key = keys.refresh_user_families_key(user_id)
        family_ids = await self._redis.smembers(user_key)
        if not family_ids:
            return []

        pipe = self._redis.pipeline(transaction=False)
        ordered = list(family_ids)
        for family_id in ordered:
            pipe.hgetall(keys.refresh_family_key(family_id))
        records = await pipe.execute()

        sessions: list[SessionInfo] = []
        stale: list[str] = []
        for family_id, record in zip(ordered, records, strict=True):
            if not record:
                stale.append(family_id)
                continue
            sessions.append(
                SessionInfo(
                    family_id=family_id,
                    device_label=record.get("device_label", "Unknown device"),
                    user_agent=record.get("user_agent", ""),
                    ip=record.get("ip", ""),
                    created_at=record.get("created_at", ""),
                    last_used_at=record.get("last_used_at", ""),
                )
            )

        if stale:
            await self._redis.srem(user_key, *stale)

        sessions.sort(key=lambda s: s.last_used_at, reverse=True)
        return sessions

    async def family_belongs_to(self, family_id: str, user_id: str) -> bool:
        """Guard so one user cannot revoke another user's device."""
        owner = await self._redis.hget(keys.refresh_family_key(family_id), "user_id")
        return owner == user_id
