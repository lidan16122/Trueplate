"""AI food detection.

The pipeline itself is not built yet. These endpoints exist now so the parts
that are easy to get wrong later — authentication, per-user rate limiting, and
the response contract the confirmation screen is built against — are settled and
exercised before any model call is wired in.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.deps import CurrentUser
from app.core.limits import AI_DETECT_SCOPE, RateLimit
from app.schemas.detection import (
    FoodDetectionResponse,
    TextDetectionRequest,
    anthropic_tool_schema,
)

router = APIRouter(prefix="/ai", tags=["ai"])

# Vision calls cost real money per request, so the limiter guards them from the
# first commit rather than being retrofitted after a surprising bill.
detect_rate_limit = RateLimit(AI_DETECT_SCOPE)

NOT_BUILT_YET = "AI food detection is not wired up yet."


@router.post(
    "/detect/photo",
    response_model=FoodDetectionResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(detect_rate_limit)],
)
async def detect_from_photo(
    user: CurrentUser,
    image: UploadFile = File(...),  # noqa: B008 - FastAPI's parameter form
) -> FoodDetectionResponse:
    """Identify foods and estimate portions from a meal photo.

    When implemented: hash the bytes, check the AI cache, otherwise call Claude
    with the ``record_detected_foods`` tool, then resolve every detected food
    against the nutrition database before returning. The model contributes
    labels and grams only.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=NOT_BUILT_YET)


@router.post(
    "/detect/text",
    response_model=FoodDetectionResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(detect_rate_limit)],
)
async def detect_from_text(
    payload: TextDetectionRequest,
    user: CurrentUser,
) -> FoodDetectionResponse:
    """Identify foods and estimate portions from a written description."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=NOT_BUILT_YET)


@router.get("/tool-schema", include_in_schema=False)
async def read_tool_schema(user: CurrentUser) -> dict:
    """The exact tool definition that will be sent to Claude.

    Exposed so the "no calorie field can reach the model" property is
    inspectable rather than a claim in a docstring.
    """
    return anthropic_tool_schema()
