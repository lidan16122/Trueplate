"""Detection workflows shared by HTTP inputs.

The API validates uploads and maps errors; these functions own cache policy,
image preparation, resolver write-backs, and the original commit boundaries.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db import transaction
from app.models.enums import DetectionMethod, MealType
from app.schemas.detection import FoodDetectionResponse, TextDetectionRequest
from app.services.detection import barcode as barcode_service
from app.services.detection import cache as detection_cache
from app.services.detection import imaging
from app.services.detection.detector import DetectionService
from app.services.nutrition import OpenFoodFactsClient

logger = logging.getLogger(__name__)


async def detect_photo(
    db: AsyncSession,
    detector: DetectionService,
    raw: bytes,
    note: str | None,
    meal_type: MealType | None,
) -> FoodDetectionResponse:
    # Hashed before downscaling, so the content address is the bytes the user
    # actually sent. Hashing the processed copy would make it depend on our own
    # resize settings, and every tweak to those would silently empty the cache.
    #
    # Two derived values, deliberately: `image_hash` travels to the client and
    # into `food_entries` as the grouping key for one photo's entries, while the
    # cache key additionally folds in the model and effort so a config change
    # cannot keep serving a stale reading.
    image_hash = detection_cache.hash_image(raw)
    cache_key = detection_cache.photo_cache_key(image_hash)
    cached = await detection_cache.read(db, cache_key)
    if cached is not None:
        await transaction.commit(db)
        return cached

    # Pillow is CPU-bound and blocking; on a single worker it would otherwise
    # stall every other in-flight request while a phone photo is resized.
    prepared = await run_in_threadpool(imaging.prepare_image, raw)

    response = await detector.detect_photo(
        prepared, note=note, meal_type=meal_type, image_hash=image_hash
    )

    if not response.is_provisional:
        # A reading we already doubt is not worth keeping for
        # `detections_ttl_days`. Cached, it would answer this photo the same way
        # every time — so a user who can see the meal was under-read has no way
        # to ask again, and "try again" replays the failure. Paying for a second
        # detection is the cheaper mistake.
        await detection_cache.write(db, cache_key, DetectionMethod.PHOTO, response)
    else:
        logger.info("Not caching a provisional reading of %s", image_hash[:12])
    # One commit covers both the cache row and anything the resolver wrote back
    # to `foods` during this request.
    await transaction.commit(db)
    return response


async def detect_text(
    db: AsyncSession,
    detector: DetectionService,
    payload: TextDetectionRequest,
) -> FoodDetectionResponse:
    cache_key = detection_cache.hash_text(payload.description, payload.meal_type)
    cached = await detection_cache.read(db, cache_key)
    if cached is not None:
        await transaction.commit(db)
        return cached

    response = await detector.detect_text(payload.description, payload.meal_type)

    # Same rule as the photo path: a reading that disagreed with its own
    # component count is not one to answer with for the next thirty days.
    if not response.is_provisional:
        await detection_cache.write(db, cache_key, DetectionMethod.TEXT, response)
    await transaction.commit(db)
    return response


async def detect_barcode(
    db: AsyncSession,
    off: OpenFoodFactsClient,
    code: str,
    raw: bytes | None,
    meal_type: MealType | None,
) -> FoodDetectionResponse:
    if not code and raw is not None:
        # Decoded from the original bytes: a barcode is fine detail, and the
        # downscale the vision path applies routinely destroys it.
        code = await run_in_threadpool(barcode_service.decode, raw) or ""

    if not code:
        # The service's own error type rather than a bare HTTPException, so
        # every barcode failure reaches the client through one mapping.
        raise barcode_service.BarcodeUnreadable(
            "No barcode found. Try again with the barcode filling more of the frame."
        )

    match, grams, serving = await barcode_service.lookup(db, off, code)

    await transaction.commit(db)
    return barcode_service.to_response(match, grams, serving, meal_type)
