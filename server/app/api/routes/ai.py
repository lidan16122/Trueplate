"""AI food detection.

Three inputs — a photo, a sentence, a barcode — that all end at the same
``FoodDetectionResponse``, so the confirmation screen never learns which one
produced it.

Auth and per-user rate limiting are dependencies rather than middleware, which
is what lets the limiter key on the authenticated user. Both run before the
handler, so a rejected request never reaches a paid model call.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.core.deps import CurrentUser, DbSession, Detector, FoodFacts
from app.core.limits import AI_DETECT_SCOPE, RateLimit, require_prompt_allowance
from app.enums import DetectionMethod, MealType
from app.schemas.detection import (
    FoodDetectionResponse,
    TextDetectionRequest,
    anthropic_tool_schema,
)
from app.services import barcode as barcode_service
from app.services import detection_cache, imaging
from app.services.detection import (
    DetectionError,
    DetectionRefused,
    NotFoodError,
    NothingDetected,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

# Vision calls cost real money per request, so the limiter guards them from the
# first commit rather than being retrofitted after a surprising bill.
detect_rate_limit = RateLimit(AI_DETECT_SCOPE)


def _translate(exc: DetectionError | barcode_service.BarcodeError) -> HTTPException:
    """Map a detection failure onto the status code it actually means.

    Kept in one place because the distinction matters to the client: the
    AddFood screen retries a 503, but shows a 422 to the user as an answer.

    Total over the two failure hierarchies it accepts, so callers can write
    ``raise _translate(exc)`` and mean it. An earlier version re-raised on the
    fallthrough, which made it a function that sometimes returned and sometimes
    threw — and left the ``raise`` at every call site unreachable for exactly
    the inputs it was written to handle.
    """
    if isinstance(exc, NotFoodError | NothingDetected | barcode_service.BarcodeError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, DetectionRefused):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    # DetectionUnavailable, and any future sibling: unreachable upstream or
    # missing configuration. 503 is the honest default for the base class.
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


async def _read_upload(image: UploadFile) -> bytes:
    if image.content_type not in imaging.ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"{image.content_type or 'That file'} is not an image we can read.",
        )
    data = await image.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="The uploaded image was empty.")
    if len(data) > settings.detect_image_max_bytes:
        # Checked after reading rather than streaming: the cap is small enough
        # that buffering it is cheaper than the complexity of a chunked guard.
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="That photo is too large. Try again at a smaller size.",
        )
    return data


@router.post(
    "/detect/photo",
    response_model=FoodDetectionResponse,
    dependencies=[Depends(detect_rate_limit), Depends(require_prompt_allowance)],
)
async def detect_from_photo(
    user: CurrentUser,
    db: DbSession,
    detector: Detector,
    image: UploadFile = File(...),  # noqa: B008 - FastAPI's parameter form
    note: str | None = Form(None),  # noqa: B008
    meal_type: MealType | None = Form(None),  # noqa: B008
) -> FoodDetectionResponse:
    """Identify foods and estimate portions from a meal photo."""
    raw = await _read_upload(image)

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
        await db.commit()
        return cached

    # Pillow is CPU-bound and blocking; on a single worker it would otherwise
    # stall every other in-flight request while a phone photo is resized.
    prepared = await run_in_threadpool(imaging.prepare_image, raw)

    try:
        response = await detector.detect_photo(
            prepared, note=note, meal_type=meal_type, image_hash=image_hash
        )
    except DetectionError as exc:
        raise _translate(exc) from exc

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
    await db.commit()
    return response


@router.post(
    "/detect/text",
    response_model=FoodDetectionResponse,
    dependencies=[Depends(detect_rate_limit), Depends(require_prompt_allowance)],
)
async def detect_from_text(
    payload: TextDetectionRequest,
    user: CurrentUser,
    db: DbSession,
    detector: Detector,
) -> FoodDetectionResponse:
    """Identify foods and estimate portions from a written description.

    Cheaper and more accurate than the camera whenever the user actually knows
    what they ate: "100 g of rice" is a fact, where any photo estimate is not.
    """
    cache_key = detection_cache.hash_text(payload.description, payload.meal_type)
    cached = await detection_cache.read(db, cache_key)
    if cached is not None:
        await db.commit()
        return cached

    try:
        response = await detector.detect_text(payload.description, payload.meal_type)
    except DetectionError as exc:
        raise _translate(exc) from exc

    # Same rule as the photo path: a reading that disagreed with its own
    # component count is not one to answer with for the next thirty days.
    if not response.is_provisional:
        await detection_cache.write(db, cache_key, DetectionMethod.TEXT, response)
    await db.commit()
    return response


@router.post(
    "/detect/barcode",
    response_model=FoodDetectionResponse,
    # No prompt allowance here, deliberately: this path never calls a model,
    # so it costs nothing against the cap and stays open to a capped account.
    dependencies=[Depends(detect_rate_limit)],
)
async def detect_from_barcode(
    user: CurrentUser,
    db: DbSession,
    off: FoodFacts,
    image: UploadFile | None = File(None),  # noqa: B008
    upc: str | None = Form(None),  # noqa: B008
    meal_type: MealType | None = Form(None),  # noqa: B008
) -> FoodDetectionResponse:
    """Resolve a packaged product from a scanned or typed barcode.

    Accepts either shape because the design asks for both: the phone sends the
    photo it just captured, the desktop sends the digits the user typed.

    No model is involved on this path at all — a UPC is an exact key, so there
    is nothing to identify and nothing to estimate.
    """
    code = (upc or "").strip()
    try:
        if not code and image is not None:
            raw = await _read_upload(image)
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
    except (DetectionError, barcode_service.BarcodeError) as exc:
        raise _translate(exc) from exc

    await db.commit()
    return barcode_service.to_response(match, grams, serving, meal_type)


@router.get("/tool-schema", include_in_schema=False)
async def read_tool_schema(user: CurrentUser) -> dict:
    """The exact tool definition that will be sent to Claude.

    Exposed so the "no calorie field can reach the model" property is
    inspectable rather than a claim in a docstring.
    """
    return anthropic_tool_schema()
