"""Session renewal, expiry, revocation, and overlapping refresh requests."""

import asyncio
import uuid

import pytest

from app.config import settings
from app.stores import keys
from app.stores.access_tokens import AccessTokenDenylist
from app.stores.refresh_tokens import RefreshTokenStore, hash_token

USER = str(uuid.uuid4())
OTHER_USER = str(uuid.uuid4())


class TestIssuing:
    async def test_raw_token_is_never_stored(self, store: RefreshTokenStore, redis):
        issued = await store.create_session(user_id=USER)
        assert await redis.exists(keys.refresh_token_key(issued.raw_token)) == 0
        record = await redis.hgetall(keys.refresh_token_key(hash_token(issued.raw_token)))
        assert record["user_id"] == USER
        assert issued.raw_token not in record.values()

    async def test_token_is_opaque_not_a_jwt(self, store: RefreshTokenStore):
        issued = await store.create_session(user_id=USER)
        assert issued.raw_token.count(".") == 0
        assert len(issued.raw_token) >= 40

    async def test_two_sessions_get_separate_families(self, store: RefreshTokenStore):
        a = await store.create_session(user_id=USER, device_label="Laptop")
        b = await store.create_session(user_id=USER, device_label="Phone")
        assert a.family_id != b.family_id
        assert a.raw_token != b.raw_token

    async def test_ttl_matches_the_configured_session_length(self, store, redis):
        issued = await store.create_session(user_id=USER)
        ttl = await redis.ttl(keys.refresh_token_key(hash_token(issued.raw_token)))
        assert settings.refresh_token_ttl_seconds - 60 < ttl <= settings.refresh_token_ttl_seconds


class TestRenewal:
    async def test_repeated_refreshes_keep_the_same_session_usable(self, store, redis):
        issued = await store.create_session(user_id=USER)
        before = set(await redis.keys("*"))
        for _ in range(5):
            result = await store.renew(issued.raw_token)
            assert result.status == "ok"
            assert result.user_id == USER
            assert result.family_id == issued.family_id

        # Refreshing must not accumulate credentials or replay records.
        assert set(await redis.keys("*")) == before

    async def test_renewal_slides_every_session_expiry(self, store, redis):
        issued = await store.create_session(user_id=USER)
        session_keys = [
            keys.refresh_token_key(hash_token(issued.raw_token)),
            keys.refresh_family_key(issued.family_id),
            keys.refresh_user_families_key(USER),
        ]
        for key in session_keys:
            await redis.expire(key, 60)

        assert (await store.renew(issued.raw_token)).status == "ok"

        for key in session_keys:
            ttl = await redis.ttl(key)
            assert (
                settings.refresh_token_ttl_seconds - 60 < ttl <= settings.refresh_token_ttl_seconds
            )

    @pytest.mark.parametrize("expired_part", ["token", "family"])
    async def test_an_expired_session_cannot_be_renewed(self, store, redis, expired_part):
        issued = await store.create_session(user_id=USER)
        expired_key = (
            keys.refresh_token_key(hash_token(issued.raw_token))
            if expired_part == "token"
            else keys.refresh_family_key(issued.family_id)
        )
        await redis.expire(expired_key, 0)

        assert (await store.renew(issued.raw_token)).status == "invalid"
        assert await redis.exists(expired_key) == 0

    @pytest.mark.parametrize("field", ["user_id", "current_token_hash"])
    async def test_a_token_must_match_its_live_family(self, store, redis, field):
        issued = await store.create_session(user_id=USER)
        await redis.hset(keys.refresh_family_key(issued.family_id), field, "another-value")

        assert (await store.renew(issued.raw_token)).status == "invalid"

    async def test_existing_deployed_sessions_survive_the_change(self, store, redis):
        # Seed the previous deployment's format, including an obsolete used-token
        # record; migration must accept only the family's current credential.
        current, consumed = "existing-current-credential", "previously-consumed-credential"
        family_id = str(uuid.uuid4())
        await redis.hset(
            keys.refresh_token_key(hash_token(current)),
            mapping={
                "user_id": USER,
                "family_id": family_id,
                "issued_at": "2026-09-20T00:00:00+00:00",
            },
        )
        await redis.hset(
            keys.refresh_family_key(family_id),
            mapping={
                "user_id": USER,
                "family_id": family_id,
                "current_token_hash": hash_token(current),
            },
        )
        await redis.hset(
            "rt:used:" + hash_token(consumed),
            mapping={
                "family_id": family_id,
                "rotated_at": "0",
            },
        )

        assert (await store.renew(current)).status == "ok"
        assert (await store.renew(consumed)).status == "invalid"
        assert (await store.renew(current)).status == "ok"


class TestConcurrency:
    async def test_parallel_refreshes_all_authenticate_the_same_session(self, store, redis):
        issued = await store.create_session(user_id=USER)

        results = await asyncio.gather(*(store.renew(issued.raw_token) for _ in range(5)))

        assert {r.status for r in results} == {"ok"}
        assert {r.family_id for r in results} == {issued.family_id}
        assert (await store.renew(issued.raw_token)).status == "ok"
        assert len(await redis.keys("rt:tok:*")) == 1

    @pytest.mark.parametrize("logout_first", [False, True])
    async def test_logout_racing_renewal_never_restores_the_session(
        self, store, redis, logout_first
    ):
        issued = await store.create_session(user_id=USER)
        operations = [store.renew(issued.raw_token), store.revoke_by_token(issued.raw_token)]
        if logout_first:
            operations.reverse()

        await asyncio.gather(*operations)

        assert (await store.renew(issued.raw_token)).status == "invalid"
        assert await redis.exists(keys.refresh_family_key(issued.family_id)) == 0
        assert await redis.exists(keys.refresh_token_key(hash_token(issued.raw_token))) == 0


class TestRevocation:
    async def test_logout_kills_the_current_device(self, store):
        issued = await store.create_session(user_id=USER)
        assert await store.revoke_by_token(issued.raw_token) is True
        assert (await store.renew(issued.raw_token)).status == "invalid"

    async def test_logout_with_an_unknown_token_is_a_no_op(self, store):
        assert await store.revoke_by_token("nonsense") is False

    async def test_one_device_cannot_revoke_another_users_session(self, store):
        issued = await store.create_session(user_id=USER)
        assert await store.revoke_family(issued.family_id, owner_id=OTHER_USER) is False
        assert (await store.renew(issued.raw_token)).status == "ok"

    async def test_revoking_a_session_leaves_other_devices_alone(self, store):
        phone = await store.create_session(user_id=USER)
        laptop = await store.create_session(user_id=USER)

        assert await store.revoke_family(phone.family_id, owner_id=USER) is True
        assert (await store.renew(phone.raw_token)).status == "invalid"
        assert (await store.renew(laptop.raw_token)).status == "ok"

    async def test_revoke_all_clears_every_device(self, store):
        a = await store.create_session(user_id=USER, device_label="Phone")
        b = await store.create_session(user_id=USER, device_label="Laptop")

        assert await store.revoke_all_for_user(USER) == 2
        assert (await store.renew(a.raw_token)).status == "invalid"
        assert (await store.renew(b.raw_token)).status == "invalid"

    async def test_revoke_all_does_not_reach_other_users(self, store):
        mine = await store.create_session(user_id=USER)
        theirs = await store.create_session(user_id=OTHER_USER)

        await store.revoke_all_for_user(USER)

        assert (await store.renew(mine.raw_token)).status == "invalid"
        assert (await store.renew(theirs.raw_token)).status == "ok"


class TestAccessDenylist:
    async def test_writes_nothing_while_disabled(self, redis):
        denylist = AccessTokenDenylist(redis)
        await denylist.revoke("some-jti", ttl_seconds=900)

        assert await denylist.is_revoked("some-jti") is False
        assert await redis.exists(keys.access_deny_key("some-jti")) == 0

    async def test_reports_revocation_when_enabled(self, redis, monkeypatch):
        monkeypatch.setattr(settings, "access_denylist_enabled", True)
        denylist = AccessTokenDenylist(redis)

        await denylist.revoke("revoked-jti", ttl_seconds=900)

        assert await denylist.is_revoked("revoked-jti") is True
        assert await denylist.is_revoked("other-jti") is False


@pytest.mark.parametrize("token", ["", "   ", "not-a-real-token"])
async def test_unknown_tokens_leave_real_sessions_usable(store, token):
    issued = await store.create_session(user_id=USER)
    assert (await store.renew(token)).status == "invalid"
    assert (await store.renew(issued.raw_token)).status == "ok"
