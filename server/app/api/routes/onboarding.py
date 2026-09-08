from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.api.errors import translate_service_error
from app.schemas.onboarding import (
    OnboardingRequest,
    OnboardingResponse,
    TargetsOut,
)
from app.services.errors import InvalidOperationError, NotFoundError
from app.services.profile import service as profile_service

router = APIRouter(tags=["profile"])


@router.post("/onboarding", response_model=OnboardingResponse, status_code=status.HTTP_201_CREATED)
async def complete_onboarding(
    payload: OnboardingRequest, user: CurrentUser, db: DbSession
) -> OnboardingResponse:
    """Persist the wizard answers and derive the first goal."""
    try:
        return await profile_service.complete_onboarding(payload, user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.post("/onboarding/preview", response_model=TargetsOut)
async def preview_targets(payload: OnboardingRequest, user: CurrentUser) -> TargetsOut:
    """Compute a target without saving anything.

    Lets the wizard show a live number as answers change, from the same code
    that will later produce the stored goal — so the preview cannot drift from
    the result.
    """
    try:
        return await profile_service.preview_targets(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
