"""End-to-end auth: sign-in, cookie flags, rotation, theft, and session listing."""

import pytest

from app.config import settings
from app.services import google_oauth
from app.services.google_oauth import GoogleAuthError
from tests.helpers import ALICE, age_tombstone, google_payload, sign_in
from tests.helpers import AUTH_API as API


class TestGoogleSignIn:
    async def test_valid_credential_creates_a_user(self, client, google_ok):
        response = await sign_in(client)

        assert response.status_code == 200
        body = response.json()
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["full_name"] == "Alice Moreno"
        assert body["user"]["initials"] == "AM"

    async def test_new_user_is_sent_to_onboarding(self, client, google_ok):
        assert (await sign_in(client)).json()["needs_onboarding"] is True

    async def test_invalid_credential_is_rejected(self, client, google_ok):
        response = await sign_in(client, "bad-token")

        assert response.status_code == 401
        assert settings.access_cookie_name not in response.cookies

    async def test_signing_in_twice_reuses_the_same_user(self, client, google_ok):
        first = (await sign_in(client)).json()["user"]["id"]
        client.cookies.clear()
        second = (await sign_in(client)).json()["user"]["id"]

        # Matching is on Google's subject, so the same person is the same row.
        assert first == second

    async def test_second_sign_in_starts_a_separate_session(self, client, google_ok, redis):
        await sign_in(client)
        client.cookies.clear()
        await sign_in(client)

        families = await redis.keys("rt:family:*")
        assert len(families) == 2


class TestCookies:
    async def test_both_tokens_are_httponly_and_secure(self, client, google_ok):
        response = await sign_in(client)
        jar = {c.split("=")[0]: c for c in response.headers.get_list("set-cookie")}

        for name in (settings.access_cookie_name, settings.refresh_cookie_name):
            raw = jar[name].lower()
            # Unreadable to JavaScript, and never sent over plaintext.
            assert "httponly" in raw
            assert "secure" in raw
            assert "samesite=lax" in raw

    async def test_refresh_cookie_is_scoped_to_the_auth_router(self, client, google_ok):
        response = await sign_in(client)
        refresh = next(
            c
            for c in response.headers.get_list("set-cookie")
            if c.startswith(settings.refresh_cookie_name)
        )
        access = next(
            c
            for c in response.headers.get_list("set-cookie")
            if c.startswith(settings.access_cookie_name)
        )

        # A 30-day credential must not ride along on every API call.
        assert f"Path={settings.refresh_cookie_path}" in refresh
        assert "Path=/" in access

    async def test_no_token_appears_in_the_response_body(self, client, google_ok):
        body = (await sign_in(client)).text
        assert "token" not in body.lower()


class TestProtectedRoutes:
    async def test_me_requires_a_session(self, client):
        assert (await client.get(f"{API}/me")).status_code == 401

    async def test_me_returns_the_signed_in_user(self, client, google_ok):
        await sign_in(client)

        response = await client.get(f"{API}/me")

        assert response.status_code == 200
        assert response.json()["user"]["email"] == "alice@example.com"

    async def test_me_reports_that_onboarding_is_still_outstanding(self, client, google_ok):
        # The client cannot work this out for itself on a reload: the cookies are
        # httpOnly, so a page load has no memory of what sign-in was told. Without
        # it, a user who closed the tab mid-wizard returns to a day view whose
        # targets do not exist.
        await sign_in(client)

        assert (await client.get(f"{API}/me")).json()["needs_onboarding"] is True

    async def test_a_tampered_token_is_rejected(self, client, google_ok):
        await sign_in(client)
        client.cookies.set(settings.access_cookie_name, "not.a.jwt")

        assert (await client.get(f"{API}/me")).status_code == 401

    async def test_a_token_signed_with_the_wrong_key_is_rejected(self, client, google_ok):
        import jwt

        await sign_in(client)
        forged = jwt.encode(
            {
                "sub": "00000000-0000-0000-0000-000000000001",
                "jti": "x",
                "typ": "access",
                "exp": 9999999999,
            },
            "an-attacker-controlled-key-of-respectable-length",
            algorithm="HS256",
        )
        client.cookies.set(settings.access_cookie_name, forged)

        assert (await client.get(f"{API}/me")).status_code == 401


class TestRefresh:
    async def test_refresh_issues_new_cookies(self, client, google_ok):
        await sign_in(client)
        before = client.cookies[settings.refresh_cookie_name]

        response = await client.post(f"{API}/refresh")

        assert response.status_code == 200
        assert client.cookies[settings.refresh_cookie_name] != before

    async def test_refresh_without_a_cookie_is_401(self, client):
        assert (await client.post(f"{API}/refresh")).status_code == 401

    async def test_session_still_works_after_refreshing(self, client, google_ok):
        await sign_in(client)
        await client.post(f"{API}/refresh")

        assert (await client.get(f"{API}/me")).status_code == 200

    async def test_concurrent_refresh_returns_409_not_401(self, client, google_ok):
        """A losing racer must not be told its session is gone."""
        await sign_in(client)
        stale = client.cookies[settings.refresh_cookie_name]

        await client.post(f"{API}/refresh")
        client.cookies.set(settings.refresh_cookie_name, stale, path=settings.refresh_cookie_path)

        response = await client.post(f"{API}/refresh")

        # 409 tells the client to retry; 401 would sign the user out for having
        # two tabs open.
        assert response.status_code == 409

    async def test_replay_after_the_grace_window_revokes_the_session(
        self, client, google_ok, redis
    ):
        await sign_in(client)
        stale = client.cookies[settings.refresh_cookie_name]

        await client.post(f"{API}/refresh")
        await age_tombstone(redis, stale)
        client.cookies.set(settings.refresh_cookie_name, stale, path=settings.refresh_cookie_path)

        response = await client.post(f"{API}/refresh")

        assert response.status_code == 401
        assert "sign in again" in response.json()["detail"].lower()

    async def test_theft_clears_the_cookies(self, client, google_ok, redis):
        await sign_in(client)
        stale = client.cookies[settings.refresh_cookie_name]
        await client.post(f"{API}/refresh")
        await age_tombstone(redis, stale)
        client.cookies.set(settings.refresh_cookie_name, stale, path=settings.refresh_cookie_path)

        response = await client.post(f"{API}/refresh")

        cleared = " ".join(response.headers.get_list("set-cookie"))
        assert settings.refresh_cookie_name in cleared
        assert "Max-Age=0" in cleared or "1970" in cleared


class TestLogout:
    async def test_logout_clears_cookies(self, client, google_ok):
        await sign_in(client)

        response = await client.post(f"{API}/logout")

        assert response.status_code == 200
        cleared = " ".join(response.headers.get_list("set-cookie"))
        assert "Max-Age=0" in cleared or "1970" in cleared

    async def test_logout_kills_the_refresh_token(self, client, google_ok):
        await sign_in(client)
        token = client.cookies[settings.refresh_cookie_name]

        await client.post(f"{API}/logout")
        client.cookies.set(settings.refresh_cookie_name, token, path=settings.refresh_cookie_path)

        assert (await client.post(f"{API}/refresh")).status_code == 401

    async def test_logout_works_without_a_valid_access_token(self, client, google_ok):
        """Signing out must succeed even after the access token has expired."""
        await sign_in(client)
        client.cookies.set(settings.access_cookie_name, "expired-nonsense")

        assert (await client.post(f"{API}/logout")).status_code == 200


class TestSessionManagement:
    async def test_lists_the_current_device(self, client, google_ok):
        await sign_in(client)

        body = (await client.get(f"{API}/sessions")).json()

        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["is_current"] is True

    async def test_device_label_is_derived_from_the_user_agent(self, client, google_ok):
        await client.post(
            f"{API}/google",
            json={"credential": "good-token"},
            headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1"},
        )

        body = (await client.get(f"{API}/sessions")).json()
        assert body["sessions"][0]["device_label"] == "Safari on iPhone"

    async def test_revoking_another_device_leaves_this_one_signed_in(self, client, google_ok):
        # First device.
        await sign_in(client)
        first = (await client.get(f"{API}/sessions")).json()["sessions"][0]["family_id"]

        # Second device signs in and becomes the current one.
        client.cookies.clear()
        await sign_in(client)

        response = await client.delete(f"{API}/sessions/{first}")

        assert response.status_code == 200
        assert (await client.get(f"{API}/me")).status_code == 200
        assert len((await client.get(f"{API}/sessions")).json()["sessions"]) == 1

    async def test_revoking_an_unknown_session_is_404(self, client, google_ok):
        await sign_in(client)

        response = await client.delete(f"{API}/sessions/00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404

    async def test_sessions_require_authentication(self, client):
        assert (await client.get(f"{API}/sessions")).status_code == 401


class TestGoogleCredentialVerification:
    """The verifier's own guards, which stubbing our function used to skip.

    Only `_verify_sync` — the signing-cert fetch — is substituted, so everything
    this module decides after that point genuinely runs.
    """

    @pytest.fixture(autouse=True)
    def client_id(self, monkeypatch):
        monkeypatch.setattr(settings, "google_client_id", "test-client-id")

    async def _verify(self, monkeypatch, **claim_overrides):
        monkeypatch.setattr(
            google_oauth, "_verify_sync", lambda credential: google_payload(**claim_overrides)
        )
        return await google_oauth.verify_google_credential("any-credential")

    async def test_a_well_formed_claim_set_is_accepted(self, monkeypatch):
        identity = await self._verify(monkeypatch)
        assert identity.subject == ALICE.subject
        assert identity.email == ALICE.email

    async def test_an_unexpected_issuer_is_rejected(self, monkeypatch):
        with pytest.raises(GoogleAuthError):
            await self._verify(monkeypatch, iss="https://evil.example.com")

    async def test_an_unverified_email_is_rejected(self, monkeypatch):
        # An unverified address could belong to someone else entirely; accepting
        # it would let an attacker claim a victim's account.
        with pytest.raises(GoogleAuthError):
            await self._verify(monkeypatch, email_verified=False)

    async def test_a_missing_email_is_rejected(self, monkeypatch):
        with pytest.raises(GoogleAuthError):
            await self._verify(monkeypatch, email="")

    async def test_the_address_is_normalised_to_lowercase(self, monkeypatch):
        identity = await self._verify(monkeypatch, email="Alice@Example.COM")
        assert identity.email == "alice@example.com"

    async def test_an_unconfigured_client_id_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "google_client_id", "")
        with pytest.raises(GoogleAuthError):
            await google_oauth.verify_google_credential("any-credential")

    async def test_a_rejected_token_does_not_leak_why(self, monkeypatch):
        def raise_value_error(credential: str):
            raise ValueError("Token has wrong audience: 12345.apps.googleusercontent.com")

        monkeypatch.setattr(google_oauth, "_verify_sync", raise_value_error)
        with pytest.raises(GoogleAuthError) as caught:
            await google_oauth.verify_google_credential("forged")

        # Telling a caller which part of a forgery failed helps them fix it.
        assert "audience" not in str(caught.value)


class TestServerErrorsDoNotLeakThroughSignIn:
    async def test_an_unconfigured_server_reports_401_without_its_reason(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(settings, "google_client_id", "")

        response = await client.post(f"{API}/google", json={"credential": "anything"})

        assert response.status_code == 401
        # "GOOGLE_CLIENT_ID is not configured on the server" is our problem to
        # read in the logs, not something to hand to an unauthenticated caller.
        assert "GOOGLE_CLIENT_ID" not in response.text
        assert "configured" not in response.text.lower()


class TestGoogleClockSkew:
    """`google-auth` defaults its skew allowance to zero.

    A token whose `iat` was one second ahead of this machine's clock came back
    as "Token used too early, 1787428240 < 1787428241" and the user simply could
    not sign in. No two clocks agree to the second, so the default rejects valid
    tokens on healthy deployments.
    """

    def test_verification_allows_for_a_clock_that_is_slightly_behind(self, monkeypatch):
        # Substituting google-auth itself, not our wrapper: the whole point is
        # which arguments cross that boundary.
        seen: dict = {}

        def fake_verify(credential, request, audience=None, **kwargs):
            seen.update(kwargs)
            return google_payload()

        monkeypatch.setattr(google_oauth.id_token, "verify_oauth2_token", fake_verify)
        monkeypatch.setattr(settings, "google_client_id", "test-client-id")

        google_oauth._verify_sync("any-credential")

        assert seen.get("clock_skew_in_seconds", 0) > 0, (
            "a zero skew allowance rejects tokens minted a second in the future"
        )

    def test_the_allowance_stays_far_below_a_token_lifetime(self):
        """It widens the expiry check too, so it must not become a real grace
        period on an hour-long token."""
        assert google_oauth.CLOCK_SKEW_SECONDS <= 60
