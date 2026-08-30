"""Helpers shared across test modules.

A plain module rather than a conftest: conftest is where pytest looks for
fixtures, and importing a function out of one works but reads as a trick. This
exists so `test_auth_routes` does not have to import from `test_refresh_tokens`
— a dependency between two test files that makes running either alone a
gamble.
"""

from datetime import UTC, datetime

from app.services.google_oauth import GoogleIdentity
from app.stores import keys
from app.stores.refresh_tokens import hash_token

AUTH_API = "/api/v1/auth"

ALICE = GoogleIdentity(
    subject="google-subject-alice",
    email="alice@example.com",
    email_verified=True,
    first_name="Alice",
    last_name="Moreno",
    picture="https://example.com/alice.jpg",
)


def google_payload(**overrides) -> dict:
    """A claim set shaped like one Google's verifier returns."""
    return {
        "iss": "https://accounts.google.com",
        "sub": ALICE.subject,
        "email": ALICE.email,
        "email_verified": True,
        "given_name": ALICE.first_name,
        "family_name": ALICE.last_name,
        "picture": ALICE.picture,
        **overrides,
    }


async def sign_in(client, credential: str = "good-token"):
    return await client.post(f"{AUTH_API}/google", json={"credential": credential})


async def age_tombstone(redis, raw_token: str, seconds: float = 3600) -> None:
    """Backdate a rotated token's tombstone past the reuse grace window.

    Replays inside the window are deliberately forgiven, so exercising genuine
    theft detection means making the rotation look old.
    """
    await redis.hset(
        keys.refresh_used_key(hash_token(raw_token)),
        "rotated_at",
        str(datetime.now(UTC).timestamp() - seconds),
    )


def set_cookie_header(response, name: str) -> str:
    """The one `Set-Cookie` line for `name`, so a test can assert on its flags.

    httpx merges the jar; the flags only exist on the raw header, and a response
    that sets three cookies has three of them.
    """
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}="):
            return header
    raise AssertionError(f"no Set-Cookie for {name!r} in {response.headers.get_list('set-cookie')}")


def set_cookie_names(response) -> set[str]:
    """Which cookies a response sets at all — the check a failure path needs."""
    return {header.split("=", 1)[0] for header in response.headers.get_list("set-cookie")}


ONBOARDING_ANSWERS = {
    "age": 32,
    "sex": "female",
    "height_cm": 172,
    "weight_kg": 74,
    "goal_type": "lose",
    "target_weight_kg": 69,
    "timezone": "Europe/Amsterdam",
}


async def complete_onboarding(client, **overrides):
    """Take the signed-in user through the wizard.

    Lives here so the auth tests can reach a *returning, onboarded* user — the
    case the redirect callback has to route to /today rather than the wizard —
    without importing from test_onboarding_routes.
    """
    return await client.post(
        "/api/v1/onboarding", json={**ONBOARDING_ANSWERS, **overrides}
    )
