"""Distinguish the anonymous page-load checks from a failed Google session."""

import uuid

import httpx
import pytest

from app.config import settings
from app.core.security import create_access_token, decode_access_token
from app.db.models import User
from tests.helpers import AUTH_API as API
from tests.helpers import complete_onboarding, sign_in


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
