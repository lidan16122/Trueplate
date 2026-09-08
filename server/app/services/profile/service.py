from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.nutrition import (
    BodyMetrics,
    age_from_birth_date,
    birth_date_from_age,
    calculate_targets,
)
from app.db import transaction
from app.db.models import User, UserProfile, WeightEntry
from app.db.repositories import profiles as repository
from app.db.repositories.goals import active_goal
from app.db.repositories.profiles import latest_weight_kg
from app.models.enums import GoalType, WeightSource
from app.schemas.onboarding import (
    GoalOut,
    OnboardingRequest,
    OnboardingResponse,
    ProfileOut,
    ProfileUpdateRequest,
    PromptLimitOut,
    TargetsOut,
)
from app.services import prompt_limits
from app.services.errors import InvalidOperationError, NotFoundError
from app.services.profile.targets import (
    metrics_for,
    recompute_and_store_goal,
    to_targets_out,
)


def _apply_name(user: User, first_name: str | None, last_name: str | None) -> None:
    """Write a corrected name, ignoring blanks.

    Both write paths prefill the field from Google, so an empty string can only
    mean the box was cleared — never a request to have no name. Storing it would
    leave the derived full name and initials with nothing to render, and
    the avatar is built from initials.

    Shared because the two routes were drifting: onboarding refused a blank
    while the profile PATCH let one through, so the same column had two rules
    depending on which screen the user happened to be on.
    """
    if first := (first_name or "").strip():
        user.first_name = first
    if last := (last_name or "").strip():
        user.last_name = last


async def complete_onboarding(
    payload: OnboardingRequest, user: User, db: AsyncSession
) -> OnboardingResponse:
    """Persist the wizard answers and derive the first goal."""
    today = datetime.now(UTC).date()

    # Names live on `users`, and `user` here is the live row — assigning to it
    # rides the same commit as the profile and the goal below.
    _apply_name(user, payload.first_name, payload.last_name)

    profile = await repository.read_profile(db, user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
        await repository.add_profile(db, profile)

    # Age in, birth date stored: see core.nutrition.birth_date_from_age for why.
    profile.birth_date = birth_date_from_age(payload.age, today)
    profile.sex = payload.sex
    profile.height_cm = payload.height_cm
    profile.activity_level = payload.activity_level
    profile.unit_preference = payload.unit_preference
    profile.timezone = payload.timezone
    await transaction.flush(db)

    # Weight is a time series; the wizard answer is simply its first point.
    existing_weight = await repository.weight_on(db, user.id, today)
    if existing_weight is None:
        await repository.add_weight(
            db,
            WeightEntry(
                user_id=user.id,
                recorded_on=today,
                weight_kg=payload.weight_kg,
                source=WeightSource.ONBOARDING,
            ),
        )
    else:
        existing_weight.weight_kg = payload.weight_kg

    goal, breakdown = await recompute_and_store_goal(
        db,
        user_id=user.id,
        profile=profile,
        weight_kg=payload.weight_kg,
        goal_type=payload.goal_type,
        target_weight_kg=payload.target_weight_kg,
        rate_kg_per_week=payload.rate_kg_per_week,
        today=today,
    )

    await transaction.commit(db)
    await transaction.refresh(db, goal)

    return OnboardingResponse(
        goal=GoalOut.model_validate(goal),
        targets=to_targets_out(breakdown, profile.sex or ""),
    )


async def preview_targets(payload: OnboardingRequest) -> TargetsOut:
    """Compute a target without saving anything.

    Lets the wizard show a live number as answers change, from the same code
    that will later produce the stored goal — so the preview cannot drift from
    the result.
    """
    breakdown = calculate_targets(
        BodyMetrics(
            weight_kg=payload.weight_kg,
            height_cm=payload.height_cm,
            age=payload.age,
            sex=payload.sex,
        ),
        goal_type=payload.goal_type,
        rate_kg_per_week=payload.rate_kg_per_week,
        target_weight_kg=payload.target_weight_kg,
        activity_level=payload.activity_level,
    )
    return to_targets_out(breakdown, payload.sex)


async def read_profile(user: User, db: AsyncSession) -> ProfileOut:
    profile = await repository.read_profile(db, user.id)
    if profile is None:
        raise NotFoundError("Profile not set up yet")

    today = datetime.now(UTC).date()
    return ProfileOut(
        first_name=user.first_name,
        last_name=user.last_name,
        age=age_from_birth_date(profile.birth_date, today) if profile.birth_date else None,
        sex=profile.sex,
        height_cm=profile.height_cm,
        weight_kg=await latest_weight_kg(db, user.id),
        activity_level=profile.activity_level,
        unit_preference=profile.unit_preference,
        timezone=profile.timezone,
    )


async def update_profile(payload: ProfileUpdateRequest, user: User, db: AsyncSession) -> TargetsOut:
    """Edit body metrics or goal, and recompute the target.

    Returns the new breakdown because every field here feeds it — the profile
    screen shows the updated number without a second request.
    """
    today = datetime.now(UTC).date()

    profile = await repository.read_profile(db, user.id)
    if profile is None:
        raise NotFoundError("Profile not set up yet")

    _apply_name(user, payload.first_name, payload.last_name)
    if payload.age is not None:
        profile.birth_date = birth_date_from_age(payload.age, today)
    if payload.sex is not None:
        profile.sex = payload.sex
    if payload.height_cm is not None:
        profile.height_cm = payload.height_cm
    if payload.activity_level is not None:
        profile.activity_level = payload.activity_level
    if payload.timezone is not None:
        profile.timezone = payload.timezone

    weight = payload.weight_kg or await latest_weight_kg(db, user.id)
    if weight is None:
        raise InvalidOperationError("No weight on record")

    if payload.weight_kg is not None:
        entry = await repository.weight_on(db, user.id, today)
        if entry is None:
            await repository.add_weight(
                db,
                WeightEntry(
                    user_id=user.id,
                    recorded_on=today,
                    weight_kg=payload.weight_kg,
                    source=WeightSource.MANUAL,
                ),
            )
        else:
            entry.weight_kg = payload.weight_kg

    current = await active_goal(db, user.id)
    goal_type = payload.goal_type or (current.goal_type if current else GoalType.MAINTAIN)
    rate = payload.rate_kg_per_week or (current.target_rate_kg_per_week if current else 0.5)
    if payload.target_weight_kg is not None:
        target_weight = payload.target_weight_kg
    elif payload.goal_type is not None:
        # The goal changed direction; the old target weight may now be on the
        # wrong side of current weight, so let it be re-derived.
        target_weight = None
    else:
        target_weight = current.target_weight_kg if current else None

    await transaction.flush(db)
    _, breakdown = await recompute_and_store_goal(
        db,
        user_id=user.id,
        profile=profile,
        weight_kg=weight,
        goal_type=goal_type,
        target_weight_kg=target_weight,
        rate_kg_per_week=rate,
        today=today,
    )

    await transaction.commit(db)
    return to_targets_out(breakdown, profile.sex or "")


async def read_targets(user: User, db: AsyncSession) -> TargetsOut:
    """The active goal, re-expressed as a full breakdown."""
    profile = await repository.read_profile(db, user.id)
    goal = await active_goal(db, user.id)
    weight = await latest_weight_kg(db, user.id)

    if profile is None or goal is None or weight is None:
        raise NotFoundError("Onboarding is not complete")

    # The stored goal is the answer, not a fresh computation. `goals` snapshots
    # its targets on purpose — they are the numbers the user is being held to —
    # and recomputing from today's weight made this route disagree with the day
    # view, which reads the snapshot, for anyone who had logged a weight since.
    # The surrounding steps are re-derived for display only; the four figures
    # that matter come off the row.
    today = datetime.now(UTC).date()
    breakdown = calculate_targets(
        metrics_for(profile, weight, today),
        goal_type=goal.goal_type,
        rate_kg_per_week=goal.target_rate_kg_per_week,
        target_weight_kg=goal.target_weight_kg,
        activity_level=profile.activity_level,
    )
    breakdown = replace(
        breakdown,
        target_calories=goal.target_calories,
        protein_g=goal.target_protein_g,
        carbs_g=goal.target_carbs_g,
        fat_g=goal.target_fat_g,
    )
    return to_targets_out(breakdown, profile.sex or "")


async def read_user_limit(user: User, db: AsyncSession) -> PromptLimitOut:
    """How many AI detections this account has spent, and whether it may spend another.

    Read by the add-food screen to disable the photo and text inputs before a
    user submits something the detect routes would only refuse. Advisory here;
    `require_prompt_allowance` is what actually holds the line.
    """
    usage = await prompt_limits.read_usage(db, user.id, user.max_prompts)
    return PromptLimitOut(allowed=usage.allowed, used=usage.used, limit=usage.limit)
