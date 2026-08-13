from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.nutrition import (
    BodyMetrics,
    age_from_birth_date,
    birth_date_from_age,
    calculate_targets,
)
from app.db.models import UserProfile, WeightEntry
from app.enums import GoalType, WeightSource
from app.schemas.onboarding import (
    GoalOut,
    OnboardingRequest,
    OnboardingResponse,
    ProfileOut,
    ProfileUpdateRequest,
    TargetsOut,
)
from app.services.targets import (
    active_goal,
    latest_weight_kg,
    metrics_for,
    recompute_and_store_goal,
    to_targets_out,
)

router = APIRouter(tags=["profile"])


@router.post("/onboarding", response_model=OnboardingResponse, status_code=status.HTTP_201_CREATED)
async def complete_onboarding(
    payload: OnboardingRequest, user: CurrentUser, db: DbSession
) -> OnboardingResponse:
    """Persist the wizard answers and derive the first goal."""
    today = datetime.now(UTC).date()

    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)

    # Age in, birth date stored: see core.nutrition.birth_date_from_age for why.
    profile.birth_date = birth_date_from_age(payload.age, today)
    profile.sex = payload.sex
    profile.height_cm = payload.height_cm
    profile.activity_level = payload.activity_level
    profile.unit_preference = payload.unit_preference
    profile.timezone = payload.timezone
    await db.flush()

    # Weight is a time series; the wizard answer is simply its first point.
    existing_weight = await db.scalar(
        select(WeightEntry).where(WeightEntry.user_id == user.id, WeightEntry.recorded_on == today)
    )
    if existing_weight is None:
        db.add(
            WeightEntry(
                user_id=user.id,
                recorded_on=today,
                weight_kg=payload.weight_kg,
                source=WeightSource.ONBOARDING,
            )
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

    await db.commit()
    await db.refresh(goal)

    return OnboardingResponse(
        goal=GoalOut.model_validate(goal),
        targets=to_targets_out(breakdown, profile.sex or ""),
    )


@router.post("/onboarding/preview", response_model=TargetsOut)
async def preview_targets(payload: OnboardingRequest, user: CurrentUser) -> TargetsOut:
    """Compute a target without saving anything.

    Lets the wizard show a live number as answers change, from the same code
    that will later produce the stored goal — so the preview cannot drift from
    the result.
    """
    try:
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
    except ValueError as exc:
        # An incoherent combination the schema cannot express on its own — a
        # lose/gain goal with a rate of zero, say. 422, not a 500.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return to_targets_out(breakdown, payload.sex)


@router.get("/profile", response_model=ProfileOut)
async def read_profile(user: CurrentUser, db: DbSession) -> ProfileOut:
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not set up yet")

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


@router.patch("/profile", response_model=TargetsOut)
async def update_profile(
    payload: ProfileUpdateRequest, user: CurrentUser, db: DbSession
) -> TargetsOut:
    """Edit body metrics or goal, and recompute the target.

    Returns the new breakdown because every field here feeds it — the profile
    screen shows the updated number without a second request.
    """
    today = datetime.now(UTC).date()

    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not set up yet")

    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No weight on record")

    if payload.weight_kg is not None:
        entry = await db.scalar(
            select(WeightEntry).where(
                WeightEntry.user_id == user.id, WeightEntry.recorded_on == today
            )
        )
        if entry is None:
            db.add(
                WeightEntry(
                    user_id=user.id,
                    recorded_on=today,
                    weight_kg=payload.weight_kg,
                    source=WeightSource.MANUAL,
                )
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

    await db.flush()
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

    await db.commit()
    return to_targets_out(breakdown, profile.sex or "")


@router.get("/profile/targets", response_model=TargetsOut)
async def read_targets(user: CurrentUser, db: DbSession) -> TargetsOut:
    """The active goal, re-expressed as a full breakdown."""
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    goal = await active_goal(db, user.id)
    weight = await latest_weight_kg(db, user.id)

    if profile is None or goal is None or weight is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding is not complete"
        )

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
