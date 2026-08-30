"""End-to-end auth: sign-in, cookie flags, rotation, theft, and session listing."""

import base64
import hashlib
from urllib.parse import unquote_plus

import httpx
import pytest

from app.api.routes import auth as auth_routes
from app.config import settings
from app.services import google_oauth
from app.services.google_oauth import GoogleAuthError
from tests import fakes
from tests.helpers import (
    ALICE,
    age_tombstone,
    complete_onboarding,
    google_payload,
    set_cookie_header,
    set_cookie_names,
    sign_in,
)
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


class TestGoogleOAuthStart:
    """The leg that sends the browser to Google.

    A plain top-level navigation, which is the entire point. The popup this
    replaces could be refused outright by the browser, with no permission in the
    Permissions API to request and no prompt to trigger.
    """

    async def test_start_sends_the_browser_to_google_with_our_client_id(
        self, client, google_token
    ):
        response = await client.get(f"{API}/google/start")

        assert response.status_code == 303
        location = httpx.URL(response.headers["location"])
        assert location.host == "accounts.google.com"
        assert location.params["client_id"] == settings.google_client_id
        assert location.params["response_type"] == "code"
        assert location.params["redirect_uri"] == settings.google_redirect_uri

    async def test_start_asks_only_for_the_claims_the_verifier_reads(self, client, google_token):
        response = await client.get(f"{API}/google/start")
        params = httpx.URL(response.headers["location"]).params

        assert params["scope"] == "openid email profile"
        # `offline` would hand us a long-lived Google refresh token to store and
        # protect, for an API this app never calls.
        assert "access_type" not in params

    async def test_the_state_cookie_is_unreadable_to_script_and_sent_on_a_lax_navigation(
        self, client, google_token
    ):
        response = await client.get(f"{API}/google/start")
        cookie = set_cookie_header(response, settings.oauth_state_cookie_name)

        assert "httponly" in cookie.lower()
        assert "secure" in cookie.lower()
        # Lax and not Strict: Google returns the user on a cross-site top-level
        # GET, which Strict is defined not to be sent on. Strict here would fail
        # every sign-in and nothing else.
        assert "samesite=lax" in cookie.lower()

    async def test_the_state_cookie_is_scoped_to_the_route_that_reads_it(
        self, client, google_token
    ):
        # The only mechanical link between OAUTH_STATE_COOKIE_PATH and the route
        # decorator. A drift between them is silent: the browser simply stops
        # sending the cookie and every sign-in fails the state check.
        response = await client.get(f"{API}/google/start")

        assert f"Path={API}/google/callback" in set_cookie_header(
            response, settings.oauth_state_cookie_name
        )

    async def test_start_binds_the_pkce_challenge_to_the_stored_verifier(
        self, client, google_token
    ):
        # Recomputed independently of the code that built it. Nothing else short
        # of the real Google would catch the challenge and the verifier drifting
        # apart — and if they do, every sign-in fails in production only.
        response = await client.get(f"{API}/google/start")
        params = httpx.URL(response.headers["location"]).params
        _, verifier = client.cookies[settings.oauth_state_cookie_name].partition(".")[::2]

        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert params["code_challenge"] == expected
        assert params["code_challenge_method"] == "S256"

    async def test_two_sign_ins_never_share_a_state(self, client, google_token):
        first = await client.get(f"{API}/google/start")
        second = await client.get(f"{API}/google/start")

        assert (
            httpx.URL(first.headers["location"]).params["state"]
            != httpx.URL(second.headers["location"]).params["state"]
        )

    async def test_an_unconfigured_server_sends_the_user_back_without_naming_the_variable(
        self, client, google_token, monkeypatch
    ):
        monkeypatch.setattr(settings, "google_client_secret", "")
        response = await client.get(f"{API}/google/start")

        assert response.status_code == 303
        assert response.headers["location"] == "/signin?error=unavailable"
        assert "SECRET" not in response.headers["location"].upper()


class TestGoogleOAuthCallback:
    """Where Google returns the user, carrying an authorization code.

    Every path answers with a redirect and none of them raise: this is the user's
    own window, so a JSON error body would be rendered to them as a bare page.
    """

    @staticmethod
    async def _callback(client, **params):
        """The leg Google sends the user back to, with whatever it carried."""
        return await client.get(f"{API}/google/callback", params=params)

    @staticmethod
    async def _start(client) -> str:
        """Walk the real start leg, and hand back the state it minted.

        Deliberately not a hand-made cookie: the value under test has to be the
        one the route actually set, or the test stops noticing when the two legs
        disagree. httpx path-matches the cookie onto the callback GET by itself.
        """
        response = await client.get(f"{API}/google/start")
        return httpx.URL(response.headers["location"]).params["state"]

    async def test_a_new_user_lands_in_the_wizard(self, client, google_token):
        state = await self._start(client)
        response = await self._callback(client, code="abc", state=state)

        # ProtectedRoute bounces a user who needs onboarding away from /today,
        # but does not bounce one who does not need it away from /onboarding —
        # so the server may only send them here when it actually computed it.
        assert response.status_code == 303
        assert response.headers["location"] == "/onboarding"

    async def test_a_successful_callback_sets_both_auth_cookies(self, client, google_token):
        state = await self._start(client)
        response = await self._callback(client, code="abc", state=state)

        names = set_cookie_names(response)
        assert settings.access_cookie_name in names
        assert settings.refresh_cookie_name in names

    async def test_a_returning_user_lands_on_today(self, client, google_token):
        # The wizard-vs-today fork is the one thing the redirect decides for
        # itself, and getting it wrong for a user who has finished onboarding
        # strands them in the wizard — ProtectedRoute only bounces the other way.
        await sign_in(client)
        await complete_onboarding(client)
        client.cookies.clear()

        state = await self._start(client)
        response = await self._callback(client, code="abc", state=state)

        assert response.headers["location"] == "/today"

    async def test_the_state_cookie_is_cleared_once_it_has_been_used(self, client, google_token):
        state = await self._start(client)
        response = await self._callback(client, code="abc", state=state)

        # Single use: leaving it live for the rest of its ten minutes would let
        # the same authorization leg be raced with a second code.
        assert "Max-Age=0" in set_cookie_header(response, settings.oauth_state_cookie_name)

    async def test_a_missing_state_cookie_is_not_a_reason_to_skip_the_check(
        self, client, google_token
    ):
        state = await self._start(client)
        client.cookies.delete(settings.oauth_state_cookie_name)

        response = await self._callback(client, code="abc", state=state)

        assert response.headers["location"] == "/signin?error=state"
        assert settings.access_cookie_name not in set_cookie_names(response)

    async def test_a_mismatched_state_sends_the_user_back_with_no_session(
        self, client, google_token
    ):
        await self._start(client)
        response = await self._callback(client, code="abc", state="not-the-state")

        assert response.headers["location"] == "/signin?error=state"
        assert settings.access_cookie_name not in set_cookie_names(response)

    async def test_a_non_ascii_state_does_not_crash_the_route(self, client, google_token):
        # `compare_digest` raises TypeError on a non-ASCII *str*, and `state` is
        # whatever the URL said. Compared as str, one chosen character turns this
        # route into an uncaught 500 — a bare error page in the user's own
        # window, which is the failure the whole route is shaped to avoid.
        await self._start(client)
        response = await self._callback(client, code="abc", state="é")

        assert response.status_code == 303
        assert response.headers["location"] == "/signin?error=state"

    async def test_a_failed_token_exchange_redirects_rather_than_raising(
        self, client, google_token
    ):
        google_token(fakes.google_token_transport(status_code=400))
        state = await self._start(client)

        response = await self._callback(client, code="abc", state=state)

        assert response.status_code == 303
        assert response.headers["location"] == "/signin?error=exchange"
        assert settings.access_cookie_name not in set_cookie_names(response)

    async def test_a_token_response_without_an_id_token_redirects(self, client, google_token):
        # A 200 with no id_token means the `openid` scope did not survive the
        # request — our bug, not the user's, and it must not read as a session.
        google_token(fakes.google_token_transport(body={"access_token": "ya29.a0"}))
        state = await self._start(client)

        response = await self._callback(client, code="abc", state=state)

        assert response.headers["location"] == "/signin?error=exchange"
        assert settings.access_cookie_name not in set_cookie_names(response)

    async def test_a_rejected_id_token_redirects_rather_than_rendering_json(
        self, client, google_token
    ):
        google_token(fakes.google_token_transport(id_token="bad-token"))
        state = await self._start(client)

        response = await self._callback(client, code="abc", state=state)

        # The window is the user's own, so a 401 JSON body would be shown to them
        # as a page.
        assert response.status_code == 303
        assert response.headers["location"] == "/signin?error=verification"
        assert settings.access_cookie_name not in set_cookie_names(response)

    async def test_a_cancelled_consent_screen_returns_to_a_clean_sign_in(
        self, client, google_token
    ):
        # Pressing Cancel is a choice, not a failure. An error note would accuse
        # the app of breaking at something the user decided not to do.
        await self._start(client)
        response = await self._callback(client, error="access_denied")

        assert response.headers["location"] == "/signin"

    async def test_a_callback_with_neither_a_code_nor_an_error_is_refused(
        self, client, google_token
    ):
        # Defaulted rather than required: a required query param raises 422
        # before the body runs, and FastAPI renders that as JSON in the window.
        state = await self._start(client)
        response = await self._callback(client, state=state)

        assert response.status_code == 303
        assert response.headers["location"] == "/signin?error=google"

    async def test_the_exchange_proves_both_the_secret_and_the_verifier(
        self, client, google_token
    ):
        seen: list[httpx.Request] = []
        google_token(fakes.google_token_transport(seen=seen))
        state = await self._start(client)
        verifier = client.cookies[settings.oauth_state_cookie_name].partition(".")[2]

        await self._callback(client, code="abc", state=state)

        sent = dict(pair.split("=", 1) for pair in seen[0].content.decode().split("&"))
        assert sent["code_verifier"] == verifier
        assert sent["client_secret"] == settings.google_client_secret
        # Google re-checks redirect_uri against the one the authorization request
        # carried. Both legs read the same setting so they cannot drift.
        assert unquote_plus(sent["redirect_uri"]) == settings.google_redirect_uri

    async def test_an_unexpected_failure_still_redirects_rather_than_500ing(
        self, client, google_token, monkeypatch
    ):
        # The route's whole promise is that nothing it does renders JSON in the
        # user's own window. Postgres and the token store are both reachable from
        # here, so without a catch-all the promise held only for the failures
        # that happened to be named.
        async def boom(*args, **kwargs):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(auth_routes, "_establish_session", boom)
        state = await self._start(client)

        response = await self._callback(client, code="abc", state=state)

        assert response.status_code == 303
        assert response.headers["location"] == "/signin?error=unavailable"
        assert settings.access_cookie_name not in set_cookie_names(response)

    async def test_a_token_response_that_is_not_an_object_redirects(self, client, google_token):
        # `.get` on a list raises AttributeError, which is not a
        # GoogleTokenExchangeError — so before the isinstance guard this escaped
        # as an uncaught 500. Sibling of the non-ASCII state above.
        google_token(fakes.google_token_transport(body=["not", "an", "object"]))
        state = await self._start(client)

        response = await self._callback(client, code="abc", state=state)

        assert response.status_code == 303
        assert response.headers["location"] == "/signin?error=exchange"
