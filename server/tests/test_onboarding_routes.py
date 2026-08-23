"""The onboarding submit: what it stores, and what it refuses to overwrite."""

from tests.helpers import sign_in

API = "/api/v1"

ANSWERS = {
    "age": 32,
    "sex": "female",
    "height_cm": 172,
    "weight_kg": 74,
    "goal_type": "lose",
    "target_weight_kg": 69,
    "timezone": "Europe/Amsterdam",
}


async def complete(client, **overrides):
    return await client.post(f"{API}/onboarding", json={**ANSWERS, **overrides})


class TestOnboardingName:
    async def test_onboarding_saves_a_corrected_name(self, client, google_ok):
        # Google supplies a name, the wizard prefills it, and the user edits it.
        # It has to persist in the same request as the rest of the answers —
        # a name saved by a separate call can succeed while onboarding fails.
        await sign_in(client)

        response = await complete(client, first_name="Alejandra", last_name="Moreno-Vidal")

        assert response.status_code == 201
        user = (await client.get(f"{API}/auth/me")).json()["user"]
        assert user["full_name"] == "Alejandra Moreno-Vidal"

    async def test_onboarding_keeps_the_google_name_when_none_is_sent(self, client, google_ok):
        await sign_in(client)

        assert (await complete(client)).status_code == 201

        user = (await client.get(f"{API}/auth/me")).json()["user"]
        assert user["full_name"] == "Alice Moreno"

    async def test_a_blank_name_does_not_erase_the_one_google_gave(self, client, google_ok):
        # An empty field is a cleared input, not a request to have no name —
        # and `initials` and the profile avatar have nothing to render without
        # one.
        await sign_in(client)

        assert (await complete(client, first_name="   ", last_name="")).status_code == 201

        user = (await client.get(f"{API}/auth/me")).json()["user"]
        assert user["full_name"] == "Alice Moreno"


class TestTargetPreview:
    async def test_preview_returns_a_target_without_storing_a_goal(self, client, google_ok):
        # The wizard's goal page shows this number live, before anything is
        # saved. If it wrote a goal, backing out of the wizard would leave one
        # behind that the user never agreed to.
        await sign_in(client)

        preview = await client.post(f"{API}/onboarding/preview", json=ANSWERS)

        assert preview.status_code == 200
        assert preview.json()["target_calories"] > 0
        assert (await client.get(f"{API}/profile/targets")).status_code == 404

    async def test_preview_and_submit_agree_on_the_target(self, client, google_ok):
        # These are the two numbers a user sees either side of one button. They
        # come from the same `calculate_targets` call, and this is what keeps
        # the wiring honest if either route grows its own preprocessing.
        await sign_in(client)

        previewed = (await client.post(f"{API}/onboarding/preview", json=ANSWERS)).json()
        saved = (await complete(client)).json()

        assert previewed["target_calories"] == saved["targets"]["target_calories"]
