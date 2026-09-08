from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.api.errors import translate_service_error
from app.schemas.onboarding import (
    ProfileOut,
    ProfileUpdateRequest,
    PromptLimitOut,
    TargetsOut,
)
from app.services.errors import InvalidOperationError, NotFoundError
from app.services.profile import service as profile_service

router = APIRouter(tags=["profile"])


@router.get("/profile", response_model=ProfileOut)
async def read_profile(user: CurrentUser, db: DbSession) -> ProfileOut:
    try:
        return await profile_service.read_profile(user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.patch("/profile", response_model=TargetsOut)
async def update_profile(
    payload: ProfileUpdateRequest, user: CurrentUser, db: DbSession
) -> TargetsOut:
    """Edit body metrics or goal, and recompute the target.

    Returns the new breakdown because every field here feeds it — the profile
    screen shows the updated number without a second request.
    """
    try:
        return await profile_service.update_profile(payload, user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.get("/profile/targets", response_model=TargetsOut)
async def read_targets(user: CurrentUser, db: DbSession) -> TargetsOut:
    """The active goal, re-expressed as a full breakdown."""
    try:
        return await profile_service.read_targets(user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.get("/profile/user-limit", response_model=PromptLimitOut)
async def read_user_limit(user: CurrentUser, db: DbSession) -> PromptLimitOut:
    """How many AI detections this account has spent, and whether it may spend another.

    Read by the add-food screen to disable the photo and text inputs before a
    user submits something the detect routes would only refuse. Advisory here;
    `require_prompt_allowance` is what actually holds the line.
    """
    try:
        return await profile_service.read_user_limit(user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc
