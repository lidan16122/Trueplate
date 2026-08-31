"""Rotation, theft detection, and the concurrency case the Lua script exists for."""

import asyncio
import uuid

import pytest

from app.config import settings
from app.stores import keys
from app.stores.access_tokens import AccessTokenDenylist
from app.stores.refresh_tokens import RefreshTokenStore, hash_token
from tests.helpers import age_tombstone

USER = str(uuid.uuid4())
OTHER_USER = str(uuid.uuid4())




class TestIssuing:
    async def test_raw_token_is_never_stored(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)

        # The raw value must not appear as a key...
        assert await redis.exists(keys.refresh_token_key(issued.raw_token)) == 0
        # ...but its hash must.
        assert await redis.exists(keys.refresh_token_key(hash_token(issued.raw_token))) == 1

    async def test_token_is_opaque_not_a_jwt(self, store: RefreshTokenStore):
        issued = await store.create_session(user_id=USER)
        assert issued.raw_token.count(".") != 2
        assert len(issued.raw_token) >= 40

    async def test_two_sessions_get_separate_families(self, store: RefreshTokenStore):
        a = await store.create_session(user_id=USER, device_label="Laptop")
        b = await store.create_session(user_id=USER, device_label="Phone")
        assert a.family_id != b.family_id
        assert a.raw_token != b.raw_token

    async def test_ttl_is_thirty_days(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        ttl = await redis.ttl(keys.refresh_token_key(hash_token(issued.raw_token)))
        assert 29 * 86400 < ttl <= 30 * 86400


class TestRotation:
    async def test_rotation_returns_a_different_token(self, store: RefreshTokenStore):
        issued = await store.create_session(user_id=USER)
        result = await store.rotate(issued.raw_token)

        assert result.status == "ok"
        assert result.user_id == USER
        assert result.raw_token != issued.raw_token

    async def test_family_survives_rotation(self, store: RefreshTokenStore):
        issued = await store.create_session(user_id=USER)
        result = await store.rotate(issued.raw_token)
        assert result.family_id == issued.family_id

    async def test_old_token_is_deleted_and_tombstoned(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        old_hash = hash_token(issued.raw_token)

        await store.rotate(issued.raw_token)

        assert await redis.exists(keys.refresh_token_key(old_hash)) == 0
        tombstone = await redis.hgetall(keys.refresh_used_key(old_hash))
        assert tombstone["family_id"] == issued.family_id
        # The timestamp is what separates a retry from a theft later on.
        assert float(tombstone["rotated_at"]) > 0

    async def test_family_points_at_the_new_token(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        result = await store.rotate(issued.raw_token)

        current = await redis.hget(keys.refresh_family_key(issued.family_id), "current_token_hash")
        assert current == hash_token(result.raw_token)

    async def test_rotation_slides_the_expiry(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        family_key = keys.refresh_family_key(issued.family_id)

        # Simulate a session most of the way through its life.
        await redis.expire(family_key, 60)
        assert await redis.ttl(family_key) <= 60

        await store.rotate(issued.raw_token)

        # An active user is never forced to re-login.
        assert await redis.ttl(family_key) > 29 * 86400

    async def test_chained_rotations_each_succeed(self, store: RefreshTokenStore):
        issued = await store.create_session(user_id=USER)
        token = issued.raw_token
        for _ in range(5):
            result = await store.rotate(token)
            assert result.status == "ok"
            token = result.raw_token


class TestReuseGraceWindow:
    """A replay moments after a rotation is a retry, not an attack."""

    async def test_immediate_replay_is_treated_as_a_retry(self, store: RefreshTokenStore):
        issued = await store.create_session(user_id=USER)
        await store.rotate(issued.raw_token)

        replay = await store.rotate(issued.raw_token)

        assert replay.status == "retry"

    async def test_retry_leaves_the_session_alive(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        rotated = await store.rotate(issued.raw_token)

        await store.rotate(issued.raw_token)  # a lagging retry

        assert await redis.exists(keys.refresh_family_key(issued.family_id)) == 1
        # And the winning token still works.
        assert (await store.rotate(rotated.raw_token)).status == "ok"


class TestTheftDetection:
    async def test_replay_after_the_grace_window_is_flagged(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        await store.rotate(issued.raw_token)
        await age_tombstone(redis, issued.raw_token)

        replay = await store.rotate(issued.raw_token)

        assert replay.status == "reuse_detected"
        assert replay.family_id == issued.family_id

    async def test_replay_revokes_the_whole_family(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        rotated = await store.rotate(issued.raw_token)
        await age_tombstone(redis, issued.raw_token)

        await store.rotate(issued.raw_token)  # the thief

        # The legitimate holder's current token is gone too — that is the point.
        assert await redis.exists(keys.refresh_token_key(hash_token(rotated.raw_token))) == 0
        assert await redis.exists(keys.refresh_family_key(issued.family_id)) == 0
        assert issued.family_id not in await redis.smembers(keys.refresh_user_families_key(USER))

    async def test_the_victims_live_token_stops_working(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        rotated = await store.rotate(issued.raw_token)
        await age_tombstone(redis, issued.raw_token)
        await store.rotate(issued.raw_token)  # theft

        assert (await store.rotate(rotated.raw_token)).status == "invalid"

    async def test_other_devices_are_left_alone(self, store: RefreshTokenStore, redis):
        phone = await store.create_session(user_id=USER, device_label="Phone")
        laptop = await store.create_session(user_id=USER, device_label="Laptop")

        await store.rotate(phone.raw_token)
        await age_tombstone(redis, phone.raw_token)
        await store.rotate(phone.raw_token)  # theft on the phone only

        # Revoking the entire *account* on one stolen token would be a denial of
        # service; only the compromised family goes.
        assert (await store.rotate(laptop.raw_token)).status == "ok"

    async def test_unknown_token_revokes_nothing(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)

        result = await store.rotate("a-string-someone-made-up")

        assert result.status == "invalid"
        assert result.family_id is None
        # Critically: the real session is untouched.
        assert await redis.exists(keys.refresh_family_key(issued.family_id)) == 1


class TestConcurrency:
    async def test_parallel_refreshes_produce_exactly_one_winner(self, store: RefreshTokenStore):
        """The race the Lua check-and-swap exists to prevent.

        Two tabs refreshing at once must not look like theft.
        """
        issued = await store.create_session(user_id=USER)

        results = await asyncio.gather(*(store.rotate(issued.raw_token) for _ in range(5)))
        statuses = [r.status for r in results]

        assert statuses.count("ok") == 1, f"expected one winner, got {statuses}"

    async def test_parallel_refreshes_do_not_revoke_the_session(
        self, store: RefreshTokenStore, redis
    ):
        issued = await store.create_session(user_id=USER)

        results = await asyncio.gather(*(store.rotate(issued.raw_token) for _ in range(5)))
        winner = next(r for r in results if r.status == "ok")

        # The losers must land on "retry", not "reuse_detected" — otherwise each
        # one revokes the family and takes the winner's brand-new token with it,
        # signing the user out for opening a second tab.
        assert {r.status for r in results} == {"ok", "retry"}
        assert await redis.exists(keys.refresh_token_key(hash_token(winner.raw_token))) == 1
        assert await redis.exists(keys.refresh_family_key(issued.family_id)) == 1

    async def test_the_winning_token_can_still_be_rotated_afterwards(
        self, store: RefreshTokenStore
    ):
        issued = await store.create_session(user_id=USER)
        results = await asyncio.gather(*(store.rotate(issued.raw_token) for _ in range(5)))
        winner = next(r for r in results if r.status == "ok")

        assert (await store.rotate(winner.raw_token)).status == "ok"


class TestRevocation:
    async def test_logout_kills_the_current_device(self, store: RefreshTokenStore):
        issued = await store.create_session(user_id=USER)
        assert await store.revoke_by_token(issued.raw_token) is True
        assert (await store.rotate(issued.raw_token)).status == "invalid"

    async def test_logout_with_an_unknown_token_is_a_no_op(self, store: RefreshTokenStore):
        assert await store.revoke_by_token("nonsense") is False

    async def test_revoke_all_clears_every_device(self, store: RefreshTokenStore):
        a = await store.create_session(user_id=USER, device_label="Phone")
        b = await store.create_session(user_id=USER, device_label="Laptop")

        assert await store.revoke_all_for_user(USER) == 2

        assert (await store.rotate(a.raw_token)).status == "invalid"
        assert (await store.rotate(b.raw_token)).status == "invalid"

    async def test_revoke_all_does_not_reach_other_users(self, store: RefreshTokenStore):
        mine = await store.create_session(user_id=USER)
        theirs = await store.create_session(user_id=OTHER_USER)

        await store.revoke_all_for_user(USER)

        assert (await store.rotate(mine.raw_token)).status == "invalid"
        assert (await store.rotate(theirs.raw_token)).status == "ok"


class TestAccessDenylist:
    async def test_writes_nothing_while_disabled(self, redis):
        denylist = AccessTokenDenylist(redis)
        await denylist.revoke("some-jti", ttl_seconds=900)

        assert await denylist.is_revoked("some-jti") is False
        # Nothing was written either: a store that records entries no reader
        # will ever consult is just a slow leak.
        assert await redis.exists(keys.access_deny_key("some-jti")) == 0

    async def test_reports_revocation_when_enabled(self, redis, monkeypatch):
        monkeypatch.setattr(settings, "access_denylist_enabled", True)
        denylist = AccessTokenDenylist(redis)

        await denylist.revoke("revoked-jti", ttl_seconds=900)

        assert await denylist.is_revoked("revoked-jti") is True
        assert await denylist.is_revoked("other-jti") is False


@pytest.mark.parametrize("token", ["", "   ", "not-a-real-token"])
async def test_garbage_tokens_are_simply_invalid(store: RefreshTokenStore, token: str):
    assert (await store.rotate(token)).status == "invalid"


class TestLogoutRacingRotation:
    """Revoking a family while a refresh is in flight must not resurrect it.

    Rotation writes the family's current token hash. If a `revoke_family` lands
    between the token lookup and that write, an unconditional HSET recreates the
    family holding only a token hash — no `user_id`, which is the field
    `revoke_family` keys off and `family_belongs_to` reads. The session would
    then outlive its own logout, unreachable by any later revoke.
    """

    async def test_rotation_does_not_recreate_a_family_revoked_mid_flight(
        self, store: RefreshTokenStore, redis
    ):
        issued = await store.create_session(user_id=USER)

        # Revoke first, then present the still-live token — the same ordering a
        # logout racing an in-flight refresh produces.
        await store.revoke_family(issued.family_id)
        result = await store.rotate(issued.raw_token)

        assert result.status != "ok", "a revoked family must not rotate"
        assert await redis.exists(keys.refresh_family_key(issued.family_id)) == 0

    async def test_no_orphan_token_survives_the_race(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        await store.revoke_family(issued.family_id)
        result = await store.rotate(issued.raw_token)

        # Whatever the outcome, no token may be left pointing at a family that
        # no longer exists.
        if getattr(result, "raw_token", None):
            assert await redis.exists(keys.refresh_token_key(hash_token(result.raw_token))) == 0
