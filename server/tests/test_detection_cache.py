"""The Postgres cache for completed detections.

Its job is to avoid paying twice for the same photo. Its risk is the mirror
image: answering the same photo the *same wrong way* for a month.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.detection import Detection
from app.enums import DetectionMethod
from app.services import detection_cache
from app.services.detection import PROMPT_FINGERPRINT


def _response(**overrides) -> dict:
    payload = {
        "detection_id": "det-1",
        "kind": "photo",
        "source_label": "From your photo",
        "meal_type": "dinner",
        "meal_description": "rice and a chicken leg",
        "items": [],
        "totals": {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0},
        "image_hash": "abc123",
        "cached": False,
        "is_provisional": False,
        "notes": None,
    }
    payload.update(overrides)
    return payload


async def test_a_stored_reading_comes_back_flagged_as_cached(db_session: AsyncSession) -> None:
    from app.schemas.detection import FoodDetectionResponse

    response = FoodDetectionResponse.model_validate(_response())
    await detection_cache.write(db_session, "key-1", DetectionMethod.PHOTO, response)

    again = await detection_cache.read(db_session, "key-1")

    assert again is not None
    assert again.cached is True
    assert again.meal_description == "rice and a chicken leg"


async def test_a_payload_from_before_the_schema_moved_is_discarded(
    db_session: AsyncSession,
) -> None:
    """The mechanism that clears readings taken under older behaviour.

    Four one-item readings of the same plate were sitting in this table, one of
    them minutes old, and every resubmission replayed them. `meal_description`
    became required precisely so those stop validating: a miss is always
    recoverable, where deserialising a stale shape is not.
    """
    stale = _response()
    del stale["meal_description"]
    db_session.add(Detection(cache_key="key-2", kind=DetectionMethod.PHOTO, payload=stale))
    await db_session.flush()

    assert await detection_cache.read(db_session, "key-2") is None
    # Deleted rather than left to be re-read and re-rejected on every request.
    assert await db_session.scalar(select(func.count()).select_from(Detection)) == 0


def test_the_key_changes_when_the_prompt_does() -> None:
    """Without this a prompt change is invisible on every photo already
    submitted — which is every photo anyone has complained about."""
    key = detection_cache.photo_cache_key("abc123")
    assert key != detection_cache._key("abc123", "claude-opus-5", "medium")  # noqa: SLF001
    assert PROMPT_FINGERPRINT
