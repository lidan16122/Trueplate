"""Presenting a target breakdown, and persisting the goal it belongs to."""

from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.nutrition import (
    BodyMetrics,
    TargetBreakdown,
    age_from_birth_date,
    calculate_targets,
)
from app.db.models import Goal, UserProfile
from app.enums import GoalType
from app.schemas.onboarding import MathRow, TargetsOut

# Stand-ins for a profile the wizard has not finished. They keep a preview
# renderable rather than 500-ing on a half-filled row; a goal is only ever
# stored once the real values are in.
FALLBACK_HEIGHT_CM = 170.0
FALLBACK_AGE = 30


def metrics_for(profile: UserProfile, weight_kg: float, today: date) -> BodyMetrics:
    """Read the BMR inputs off a profile row.

    One place, because the profile's three nullable columns need the same
    defaulting everywhere they are read — and `BodyMetrics` rejects the zeros
    that a bare `or 0` would have produced.
    """
    return BodyMetrics(
        weight_kg=weight_kg,
        height_cm=profile.height_cm or FALLBACK_HEIGHT_CM,
        age=age_from_birth_date(profile.birth_date, today) if profile.birth_date else FALLBACK_AGE,
        sex=profile.sex,
    )


def _goal_sentence(t: TargetBreakdown) -> str:
    if t.goal_type == GoalType.MAINTAIN:
        return (
            "Eating at this number should hold your weight steady at your current activity level."
        )

    verb = "lost" if t.goal_type == GoalType.LOSE else "gained"
    weeks = "week" if t.weeks_to_target == 1 else "weeks"
    return (
        f"Eating at this number puts you on track for about "
        f"{t.rate_kg_per_week:.1f} kg {verb} per week, reaching "
        f"{t.target_weight_kg:.1f} kg in roughly {t.weeks_to_target} {weeks}. "
        f"Going over on a given day is data, not a failure."
    )


def _math_rows(t: TargetBreakdown, sex: str) -> list[MathRow]:
    sex_note = "male" if sex == "male" else "female"
    if t.delta == 0:
        adjustment_label = "No adjustment (maintaining)"
    else:
        word = "Deficit" if t.delta < 0 else "Surplus"
        adjustment_label = f"{word} for a steady {t.rate_kg_per_week:.1f} kg per week"

    return [
        MathRow(label=f"Resting burn (Mifflin-St Jeor, {sex_note})", value=f"{t.bmr:,} kcal"),
        MathRow(label="Everyday activity allowance", value=f"× {t.activity_factor}"),
        MathRow(label="Estimated daily burn", value=f"{t.tdee:,} kcal"),
        MathRow(label=adjustment_label, value=f"{t.delta:+,} kcal"),
        MathRow(label="Daily target", value=f"{t.target_calories:,} kcal"),
    ]


def to_targets_out(t: TargetBreakdown, sex: str) -> TargetsOut:
    return TargetsOut(
        bmr=t.bmr,
        activity_factor=t.activity_factor,
        tdee=t.tdee,
        delta=t.delta,
        target_calories=t.target_calories,
        protein_g=t.protein_g,
        carbs_g=t.carbs_g,
        fat_g=t.fat_g,
        goal_type=t.goal_type,
        rate_kg_per_week=t.rate_kg_per_week,
        target_weight_kg=t.target_weight_kg,
        weeks_to_target=t.weeks_to_target,
        math_rows=_math_rows(t, sex),
        summary=_goal_sentence(t),
    )


async def latest_weight_kg(session: AsyncSession, user_id) -> float | None:
    from app.db.models import WeightEntry

    return await session.scalar(
        select(WeightEntry.weight_kg)
        .where(WeightEntry.user_id == user_id)
        .order_by(WeightEntry.recorded_on.desc())
        .limit(1)
    )


async def active_goal(session: AsyncSession, user_id) -> Goal | None:
    return await session.scalar(select(Goal).where(Goal.user_id == user_id, Goal.ends_on.is_(None)))


async def recompute_and_store_goal(
    session: AsyncSession,
    *,
    user_id,
    profile: UserProfile,
    weight_kg: float,
    goal_type: str,
    target_weight_kg: float | None,
    rate_kg_per_week: float,
    today: date | None = None,
) -> tuple[Goal, TargetBreakdown]:
    """Close any open goal and open a new one carrying the recomputed targets.

    Superseding rather than mutating: a day logged last month was judged against
    the target in force then, and editing the old row in place would silently
    rewrite that history.
    """
    today = today or datetime.now(UTC).date()

    breakdown = calculate_targets(
        metrics_for(profile, weight_kg, today),
        goal_type=goal_type,
        rate_kg_per_week=rate_kg_per_week,
        target_weight_kg=target_weight_kg,
        activity_level=profile.activity_level,
    )

    # `ends_on` is exclusive and `starts_on` inclusive, so [starts_on, ends_on)
    # of the closed row and the new one do not overlap even though both carry
    # today's date. Two edits in one day leave a zero-length row, which is the
    # honest record: that goal never governed a whole day.
    await session.execute(
        update(Goal).where(Goal.user_id == user_id, Goal.ends_on.is_(None)).values(ends_on=today)
    )

    goal = Goal(
        user_id=user_id,
        goal_type=goal_type,
        target_weight_kg=breakdown.target_weight_kg,
        target_rate_kg_per_week=rate_kg_per_week,
        target_calories=breakdown.target_calories,
        target_protein_g=breakdown.protein_g,
        target_carbs_g=breakdown.carbs_g,
        target_fat_g=breakdown.fat_g,
        starts_on=today,
    )
    session.add(goal)
    return goal, breakdown
