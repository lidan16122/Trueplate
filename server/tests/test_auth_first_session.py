"""Distinguish the anonymous page-load checks from a failed Google session."""

import uuid

import httpx
import pytest
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import AuthenticationError, AuthorizationError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import settings
from app.core.security import create_access_token, decode_access_token
from app.db.models import User
from app.stores import keys
from tests import fakes
from tests.helpers import AUTH_API as API
from tests.helpers import complete_onboarding, set_cookie_names, sign_in


@pytest.fixture
def fail_session_writes(redis, monkeypatch):
    """Interrupt Redis transport while keeping the real pipeline and transaction behavior."""
    # The production pool has no automatic command retries; fakeredis's client default differs.
    redis.connection_pool.set_retry(Retry(NoBackoff(), 0))
    connection_type = redis.connection_pool.connection_class
    send = connection_type.send_packed_command

    def install(*, failures=1, after_write=False, error_type=RedisConnectionError):
        attempts = []

        async def interrupted_send(connection, command, **kwargs):
            packed = b"".join(command)
            if b"MULTI" not in packed:
                return await send(connection, command, **kwargs)
            attempts.append(packed)
            if len(attempts) > failures:
                return await send(connection, command, **kwargs)
            if after_write:
                # fakeredis executes MULTI/EXEC here; disconnect then discards only the reply.
                await send(connection, command, **kwargs)
            raise error_type("Error UNKNOWN while writing to socket. Connection lost.")

        monkeypatch.setattr(connection_type, "send_packed_command", interrupted_send)
        return attempts

    return install


@pytest.mark.parametrize("returning_user", [False, True], ids=["new-user", "returning-user"])
@pytest.mark.parametrize("after_write", [False, True], ids=["lost-write", "lost-reply"])
@pytest.mark.parametrize("error_type", [RedisConnectionError, RedisTimeoutError])
async def test_google_callback_recovers_when_redis_disconnects_during_session_creation(
    client, google_token, redis, fail_session_writes, returning_user, after_write, error_type
):
    if returning_user:
        await sign_in(client)
        await complete_onboarding(client)
        client.cookies.clear()
    existing_families = set(await redis.keys(f"{keys.REFRESH_FAMILY_PREFIX}*"))
    attempts = fail_session_writes(after_write=after_write, error_type=error_type)
    exchanges = []
    google_token(fakes.google_token_transport(seen=exchanges))

    start = await client.get(f"{API}/google/start")
    state = httpx.URL(start.headers["location"]).params["state"]

    callback = await client.get(f"{API}/google/callback", params={"code": "abc", "state": state})

    assert callback.status_code == 303
    assert callback.headers["location"] == ("/today" if returning_user else "/onboarding")
    session = await client.get(f"{API}/session")
    assert session.status_code == 200
    assert session.json()["user"]["email"] == "alice@example.com"
    assert len(exchanges) == 1
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    claims = decode_access_token(client.cookies[settings.access_cookie_name])
    assert set(await redis.keys(f"{keys.REFRESH_FAMILY_PREFIX}*")) == existing_families | {
        keys.refresh_family_key(claims.session_id)
    }
    client.cookies.delete(settings.access_cookie_name)
    assert (await client.post(f"{API}/refresh")).status_code == 200
    assert (await client.get(f"{API}/session")).json() == session.json()
    assert (await client.post(f"{API}/logout")).status_code == 200
    assert await redis.exists(keys.refresh_family_key(claims.session_id)) == 0


@pytest.mark.parametrize("error_type", [RedisConnectionError, RedisTimeoutError])
async def test_a_persistent_redis_failure_stops_after_one_retry_without_auth_cookies(
    client, google_token, fail_session_writes, error_type
):
    attempts = fail_session_writes(failures=10, error_type=error_type)
    start = await client.get(f"{API}/google/start")
    state = httpx.URL(start.headers["location"]).params["state"]

    callback = await client.get(f"{API}/google/callback", params={"code": "abc", "state": state})

    assert callback.headers["location"] == "/signin?error=unavailable"
    assert len(attempts) == 2
    assert settings.access_cookie_name not in set_cookie_names(callback)
    assert settings.refresh_cookie_name not in set_cookie_names(callback)
    assert (await client.get(f"{API}/session")).json() is None

    # The account was already saved before Redis failed; a fresh attempt must still sign it in.
    fail_session_writes(failures=0)
    start = await client.get(f"{API}/google/start")
    state = httpx.URL(start.headers["location"]).params["state"]
    recovered = await client.get(f"{API}/google/callback", params={"code": "new", "state": state})
    assert recovered.headers["location"] == "/onboarding"
    assert (await client.get(f"{API}/session")).json()["user"]["email"] == "alice@example.com"


@pytest.mark.parametrize("error_type", [AuthenticationError, AuthorizationError, ResponseError])
async def test_a_redis_configuration_or_command_error_is_not_retried(
    client, google_token, fail_session_writes, error_type
):
    attempts = fail_session_writes(error_type=error_type)
    start = await client.get(f"{API}/google/start")
    state = httpx.URL(start.headers["location"]).params["state"]

    callback = await client.get(f"{API}/google/callback", params={"code": "abc", "state": state})

    assert callback.headers["location"] == "/signin?error=unavailable"
    assert len(attempts) == 1
    assert settings.access_cookie_name not in set_cookie_names(callback)
    assert settings.refresh_cookie_name not in set_cookie_names(callback)


@pytest.mark.parametrize("returning_user", [False, True], ids=["new-user", "returning-user"])
async def test_anonymous_startup_and_first_google_sign_in_need_no_refresh(
    client, google_token, returning_user
):
    if returning_user:
        await sign_in(client)
        await complete_onboarding(client)
        client.cookies.clear()

    anonymous_session = await client.get(f"{API}/session")
    assert anonymous_session.status_code == 200
    assert anonymous_session.json() is None
    assert anonymous_session.headers["cache-control"] == "no-store"
    assert "set-cookie" not in anonymous_session.headers

    start = await client.get(f"{API}/google/start")
    assert start.status_code == 303
    state = httpx.URL(start.headers["location"]).params["state"]
    callback = await client.get(f"{API}/google/callback", params={"code": "abc", "state": state})
    assert callback.status_code == 303
    assert callback.headers["location"] == ("/today" if returning_user else "/onboarding")

    # A redirect alone does not prove sign-in worked; its cookies must authenticate
    # the next page's session check through the same HTTP cookie jar.
    signed_in_me = await client.get(f"{API}/session")
    assert signed_in_me.status_code == 200
    assert signed_in_me.json()["user"]["email"] == "alice@example.com"
    assert signed_in_me.json()["needs_onboarding"] is (not returning_user)
    assert signed_in_me.headers["cache-control"] == "no-store"
    assert "set-cookie" not in signed_in_me.headers

    # Losing the access cookie must still leave the callback's refresh cookie usable.
    client.cookies.delete(settings.access_cookie_name)
    assert (await client.get(f"{API}/session")).status_code == 401
    assert (await client.post(f"{API}/refresh")).status_code == 200
    refreshed_me = await client.get(f"{API}/session")
    assert refreshed_me.status_code == 200
    assert refreshed_me.json() == signed_in_me.json()


async def test_an_invalid_access_cookie_without_refresh_is_anonymous(client):
    client.cookies.set(settings.access_cookie_name, "not.a.jwt")

    response = await client.get(f"{API}/session")

    assert response.status_code == 200
    assert response.json() is None
    assert (await client.get(f"{API}/me")).status_code == 401


async def test_refresh_authenticates_even_if_another_tabs_response_has_not_arrived(
    client, google_ok
):
    await sign_in(client)
    refresh = client.cookies[settings.refresh_cookie_name]
    client.cookies.delete(settings.access_cookie_name)

    # Both tabs sent the same cookie before either response arrived. The first
    # response's Set-Cookie headers may still be in transit when the second finishes.
    first = await client.post(f"{API}/refresh")
    assert first.status_code == 200
    client.cookies.clear()
    client.cookies.set(settings.refresh_cookie_name, refresh, path=settings.refresh_cookie_path)

    second = await client.post(f"{API}/refresh")

    session = await client.get(f"{API}/session")
    assert session.status_code == 200
    assert session.json()["user"]["email"] == "alice@example.com"
    assert second.status_code == 200


@pytest.mark.parametrize("refresh_available", [False, True])
async def test_expired_access_only_requests_recovery_when_refresh_is_available(
    client, google_ok, monkeypatch, refresh_available
):
    await sign_in(client)
    claims = decode_access_token(client.cookies[settings.access_cookie_name])
    with monkeypatch.context() as expired_settings:
        expired_settings.setattr(settings, "access_token_ttl_minutes", -1)
        expired = create_access_token(user_id=claims.user_id, session_id=claims.session_id)
    access_cookie = next(c for c in client.cookies.jar if c.name == settings.access_cookie_name)
    access_cookie.value = expired.token
    if not refresh_available:
        client.cookies.delete(settings.refresh_cookie_name)

    response = await client.get(f"{API}/session")

    if not refresh_available:
        assert response.status_code == 200
        assert response.json() is None
        return

    assert response.status_code == 401
    assert (await client.post(f"{API}/refresh")).status_code == 200
    restored = await client.get(f"{API}/session")
    assert restored.status_code == 200
    assert restored.json()["user"]["id"] == claims.user_id


async def test_a_deactivated_user_is_never_exposed_by_session_discovery(
    client, google_ok, db_session
):
    response = await sign_in(client)
    user = await db_session.get(User, uuid.UUID(response.json()["user"]["id"]))
    user.is_active = False
    await db_session.commit()
    client.cookies.delete(settings.refresh_cookie_name)

    response = await client.get(f"{API}/session")

    assert response.status_code == 200
    assert response.json() is None
    assert (await client.get(f"{API}/me")).status_code == 401


async def test_session_discovery_does_not_hide_database_failure(
    client, google_ok, db_session, monkeypatch
):
    await sign_in(client)

    async def unavailable(*args, **kwargs):
        raise ConnectionError("Database unavailable")

    monkeypatch.setattr(db_session, "get", unavailable)
    with pytest.raises(ConnectionError, match="Database unavailable"):
        await client.get(f"{API}/session")
