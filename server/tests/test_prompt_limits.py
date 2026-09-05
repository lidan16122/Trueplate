"""The lifetime cap on AI detections: how it is counted, and who enforces it.

A cap the client alone honours is not a cap, so these cover both halves — what
`/profile/user-limit` reports to the add-food screen, and what `/ai/detect/*`
does to a request that ignores it.
"""

import io
from datetime import UTC, datetime

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_detection_service
from app.db.models import User
from app.main import app as fastapi_app
from app.services.detection import NotFoodError
from tests.helpers import sign_in

API = "/api/v1"


def entry(**overrides) -> dict:
    """One confirmed item, shaped as the confirm screen sends it."""
    return {
        "name": "Rice",
        "meal_type": "lunch",
        "quantity_g": 150,
        "kcal_per_100g": 130,
        "detection_method": "photo",
        "nutrition_source": "usda_fdc",
        **overrides,
    }


async def log(client, *entries) -> None:
    today = datetime.now(UTC).date().isoformat()
    response = await client.post(f"{API}/logs/{today}/entries", json={"entries": list(entries)})
    assert response.status_code == 201, response.text


async def set_cap(db: AsyncSession, max_prompts: int | None) -> None:
    """The only way to move the cap — it has no API surface of its own."""
    user = await db.scalar(select(User))
    user.max_prompts = max_prompts
    await db.commit()


def jpeg() -> bytes:
    """A real image, so a request that clears the gate fails further on for a
    reason of its own rather than on Pillow refusing the bytes."""
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), (180, 140, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def read_limit(client) -> dict:
    response = await client.get(f"{API}/profile/user-limit")
    assert response.status_code == 200, response.text
    return response.json()


class TestCounting:
    async def test_a_new_account_carries_the_column_default(self, client, google_ok):
        # Pins the default rather than assuming it: `max_prompts` is set
        # Python-side on the model, and the migration adds no server default, so
        # every account created from here is capped where this says it is.
        await sign_in(client)

        assert await read_limit(client) == {"allowed": True, "used": 0, "limit": 1}

    async def test_an_account_with_no_cap_is_never_blocked(self, client, db_session, google_ok):
        # Null is what every account created before the column existed holds.
        # Reading that as a cap of zero would lock out the entire existing user
        # base on deploy.
        await sign_in(client)
        await set_cap(db_session, None)
        await log(client, entry(image_hash="a" * 64), entry(detection_method="text"))

        assert await read_limit(client) == {"allowed": True, "used": 2, "limit": None}

    async def test_one_photo_of_several_foods_spends_a_single_detection(
        self, client, db_session, google_ok
    ):
        # The reason the count folds on `image_hash` at all. Counting rows, a
        # plate of rice, chicken and broccoli would spend three prompts on the
        # first meal anyone photographs.
        await sign_in(client)
        await set_cap(db_session, 2)
        await log(
            client,
            entry(name="Rice", image_hash="b" * 64),
            entry(name="Chicken", image_hash="b" * 64),
            entry(name="Broccoli", image_hash="b" * 64),
        )

        assert await read_limit(client) == {"allowed": True, "used": 1, "limit": 2}

    async def test_two_photos_spend_two_detections(self, client, db_session, google_ok):
        await sign_in(client)
        await set_cap(db_session, 2)
        await log(client, entry(image_hash="c" * 64), entry(image_hash="d" * 64))

        assert await read_limit(client) == {"allowed": False, "used": 2, "limit": 2}

    async def test_a_barcode_entry_does_not_spend_a_detection(
        self, client, db_session, google_ok
    ):
        # Nothing on the barcode path calls a model, so it costs nothing — which
        # is what makes it the honest escape hatch the UI offers a capped user.
        await sign_in(client)
        await set_cap(db_session, 1)
        await log(client, entry(detection_method="barcode", nutrition_source="open_food_facts"))

        assert await read_limit(client) == {"allowed": True, "used": 0, "limit": 1}

    async def test_a_manual_entry_does_not_spend_a_detection(self, client, db_session, google_ok):
        await sign_in(client)
        await set_cap(db_session, 1)
        await log(client, entry(detection_method="manual", nutrition_source="manual"))

        assert (await read_limit(client))["used"] == 0


class TestEnforcement:
    """The gate the client's disabled buttons are only a courtesy for."""

    async def test_the_photo_route_refuses_a_detection_once_the_cap_is_spent(
        self, client, db_session, google_ok
    ):
        await sign_in(client)
        await set_cap(db_session, 1)
        await log(client, entry(image_hash="e" * 64))

        refused = await client.post(
            f"{API}/ai/detect/photo",
            files={"image": ("meal.jpg", jpeg(), "image/jpeg")},
        )

        # 403, not 429: the limiter's "try again shortly" is the opposite of
        # what is true here — no amount of waiting returns the allowance.
        assert refused.status_code == 403
        assert "AI detections" in refused.json()["detail"]

    async def test_the_text_route_refuses_a_detection_once_the_cap_is_spent(
        self, client, db_session, google_ok
    ):
        await sign_in(client)
        await set_cap(db_session, 1)
        await log(client, entry(detection_method="text"))

        refused = await client.post(f"{API}/ai/detect/text", json={"description": "a bowl of rice"})

        assert refused.status_code == 403

    async def test_a_barcode_lookup_is_not_refused_at_the_cap(
        self, client, db_session, google_ok
    ):
        # The empty-code 422 is incidental; what this pins is that the cap does
        # not stand between a capped user and the one path that costs nothing.
        await sign_in(client)
        await set_cap(db_session, 1)
        await log(client, entry(image_hash="f" * 64))

        response = await client.post(f"{API}/ai/detect/barcode", data={"upc": ""})

        assert response.status_code == 422

    async def test_an_uncapped_account_reaches_the_detector(self, client, db_session, google_ok):
        # Without this the 403s above would still pass if the dependency simply
        # refused every request. Substituting the detector — the boundary in
        # front of the Anthropic SDK — is what keeps this from making a real
        # call; the 422 it produces is proof the request got past the gate and
        # into the handler.
        await sign_in(client)
        await set_cap(db_session, None)
        await log(client, entry(image_hash="0" * 64))
        fastapi_app.dependency_overrides[get_detection_service] = lambda: _RefusingDetector()

        response = await client.post(
            f"{API}/ai/detect/photo",
            files={"image": ("meal.jpg", jpeg(), "image/jpeg")},
        )

        assert response.status_code == 422


class _RefusingDetector:
    """A detector that answers without a model call, for the one test that has
    to reach past the gate."""

    async def detect_photo(self, *args, **kwargs):
        raise NotFoodError("That does not look like food.")
