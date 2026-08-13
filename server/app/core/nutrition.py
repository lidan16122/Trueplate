"""Calorie and macro target derivation.

Pure functions over raw inputs — no I/O, no ORM. What gets *persisted* is the
inputs (birth date, sex, height, weight, goal, rate), never the numbers computed
here, so swapping the equation changes future targets without rewriting a single
logged day. Age is the one value that arrives as an integer and is stored as a
birth date, because an age goes stale where a date does not.

This module is the only place these numbers are produced. The target-reveal
screen renders what the server returns rather than recomputing it, so there is
no second implementation to drift out of agreement with this one.
"""

import math
from dataclasses import dataclass
from datetime import date

from app.enums import ActivityLevel, GoalType, Sex

# kcal per kg of body mass. The conventional figure behind "500 kcal/day ≈
# 0.45 kg/week"; kept as a named constant because it is an estimate, not a law.
KCAL_PER_KG = 7700.0

# Multipliers applied to BMR. The onboarding wizard has no activity step and the
# design fixes the factor at 1.375 — exactly LIGHT, which is therefore the default.
ACTIVITY_FACTORS: dict[str, float] = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHT: 1.375,
    ActivityLevel.MODERATE: 1.55,
    ActivityLevel.VERY: 1.725,
    ActivityLevel.EXTRA: 1.9,
}

# A floor, not a recommendation. Below roughly this, a target stops being a
# deficit and starts being a diet no one should follow unsupervised.
MIN_TARGET_KCAL = 1200

KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_CARB = 4
KCAL_PER_G_FAT = 9

# Protein scales with body mass; fat takes a share of the calorie target and
# carbohydrate fills whatever is left. Gaining tolerates more protein and less
# fat, because the surplus has to go somewhere useful.
PROTEIN_G_PER_KG_GAIN = 2.2
PROTEIN_G_PER_KG_ELSE = 1.8
FAT_SHARE_OF_TARGET_GAIN = 0.22
FAT_SHARE_OF_TARGET_ELSE = 0.28

# Rounded to the nearest 10 kcal: the inputs are estimates, and a target of
# "1500" reads as guidance where "1504" reads as a measurement.
TARGET_ROUNDING_KCAL = 10

DAYS_PER_WEEK = 7

# Default distance to a target weight when the user states none.
DEFAULT_TARGET_WEIGHT_DELTA_KG = 5.0


def _round_half_up(value: float) -> int:
    """Round halves upward, i.e. toward positive infinity.

    Python's built-in ``round`` uses banker's rounding, so 2.5 -> 2 and 3.5 -> 4.
    Users read that as a bug: two adjacent targets round in opposite directions
    for no visible reason. Halves here always go up, which is also what
    JavaScript's ``Math.round`` does, so a number quoted in a client-side
    comparison lands the same way.
    """
    return math.floor(value + 0.5)


@dataclass(frozen=True, slots=True)
class BodyMetrics:
    """The four inputs Mifflin-St Jeor needs.

    They travel together everywhere, so they are one type rather than four
    parameters repeated at each call site and reassembled in each test.

    Validated on construction: a profile can reach here half-filled (the wizard
    saves step by step), and a zero height silently yields a negative BMR that
    the calorie floor then hides.
    """

    weight_kg: float
    height_cm: float
    age: int
    sex: Sex | None = None

    def __post_init__(self) -> None:
        if self.weight_kg <= 0:
            raise ValueError(f"weight_kg must be positive, got {self.weight_kg}")
        if self.height_cm <= 0:
            raise ValueError(f"height_cm must be positive, got {self.height_cm}")
        if not 0 < self.age < 130:
            raise ValueError(f"age must be between 1 and 129, got {self.age}")


@dataclass(frozen=True, slots=True)
class TargetBreakdown:
    """Every intermediate value the target-reveal screen displays.

    ``tdee + delta`` reaches ``target_calories`` to within the 10 kcal the target
    is rounded to — and exactly, when the calorie floor binds. The screen shows
    those three as an equation, so the floor case has to reconcile: there the
    requested deficit and the applied one differ by hundreds, not by rounding.
    """

    bmr: int
    activity_factor: float
    tdee: int
    delta: int
    target_calories: int
    protein_g: int
    carbs_g: int
    fat_g: int
    goal_type: GoalType
    rate_kg_per_week: float
    target_weight_kg: float
    weeks_to_target: int


def age_from_birth_date(birth_date: date, today: date | None = None) -> int:
    today = today or date.today()
    had_birthday = (today.month, today.day) >= (birth_date.month, birth_date.day)
    return today.year - birth_date.year - (0 if had_birthday else 1)


def birth_date_from_age(age: int, today: date | None = None) -> date:
    """Approximate a birth date from a stated age.

    The wizard asks for age, but age is a value that goes stale. Anchoring it to
    a date means it stays correct as time passes; the day-of-year is a guess
    until the user edits it, which costs at most a few months of precision in a
    formula whose age term is worth 5 kcal per year.
    """
    today = today or date.today()
    try:
        return today.replace(year=today.year - age)
    except ValueError:
        # 29 February in a non-leap target year.
        return today.replace(year=today.year - age, day=28)


def basal_metabolic_rate(metrics: BodyMetrics) -> float:
    """Mifflin-St Jeor resting energy expenditure, unrounded."""
    base = 10.0 * metrics.weight_kg + 6.25 * metrics.height_cm - 5.0 * metrics.age
    if metrics.sex == Sex.MALE:
        return base + 5.0
    if metrics.sex == Sex.FEMALE:
        return base - 161.0
    # Unstated sex — the column is nullable and onboarding may skip it. Take the
    # midpoint of the two rather than silently assuming one.
    return base + (5.0 - 161.0) / 2.0


def activity_factor(activity_level: str | None) -> float:
    return ACTIVITY_FACTORS.get(activity_level or "", ACTIVITY_FACTORS[ActivityLevel.LIGHT])


def _macros_for(target_calories: int, weight_kg: float, gaining: bool) -> tuple[int, int, int]:
    """Split a calorie target into protein, carbohydrate, and fat grams.

    The three always reconcile to ``target_calories``. Protein is derived from
    body mass and fat from a share of the target, so for a heavy person on a
    steep deficit the two alone can exceed the whole target — at which point
    carbohydrate cannot absorb the difference by going negative. Scaling protein
    and fat down to fit keeps the calorie target authoritative, which is what the
    UI shows beside them.
    """
    protein_g = _round_half_up(
        weight_kg * (PROTEIN_G_PER_KG_GAIN if gaining else PROTEIN_G_PER_KG_ELSE)
    )
    fat_share = FAT_SHARE_OF_TARGET_GAIN if gaining else FAT_SHARE_OF_TARGET_ELSE
    fat_g = _round_half_up(target_calories * fat_share / KCAL_PER_G_FAT)

    fixed_kcal = protein_g * KCAL_PER_G_PROTEIN + fat_g * KCAL_PER_G_FAT
    if fixed_kcal > target_calories:
        shrink = target_calories / fixed_kcal
        protein_g = _round_half_up(protein_g * shrink)
        fat_g = _round_half_up(fat_g * shrink)
        fixed_kcal = protein_g * KCAL_PER_G_PROTEIN + fat_g * KCAL_PER_G_FAT

    carbs_g = max(0, _round_half_up((target_calories - fixed_kcal) / KCAL_PER_G_CARB))
    return protein_g, carbs_g, fat_g


def calculate_targets(
    metrics: BodyMetrics,
    *,
    goal_type: GoalType,
    rate_kg_per_week: float = 0.5,
    target_weight_kg: float | None = None,
    activity_level: str | None = None,
) -> TargetBreakdown:
    """Derive a calorie target and macro split from body metrics and a goal.

    Raises ``ValueError`` on an incoherent goal rather than returning a number.
    A rate of zero on a lose/gain goal has no answer — the old code divided by it
    — and a negative rate reverses the sign of the deficit, quietly turning a
    weight-loss goal into a surplus.
    """
    if goal_type is not GoalType.MAINTAIN and rate_kg_per_week <= 0:
        raise ValueError(
            f"a {goal_type} goal needs a positive rate_kg_per_week, got {rate_kg_per_week}"
        )

    bmr = basal_metabolic_rate(metrics)
    factor = activity_factor(activity_level)
    tdee = bmr * factor

    if goal_type is GoalType.MAINTAIN:
        delta = 0.0
    else:
        direction = -1.0 if goal_type is GoalType.LOSE else 1.0
        delta = direction * (rate_kg_per_week * KCAL_PER_KG / DAYS_PER_WEEK)

    rounded_tdee = _round_half_up(tdee)
    raw_target = _round_half_up((tdee + delta) / TARGET_ROUNDING_KCAL) * TARGET_ROUNDING_KCAL
    target = max(MIN_TARGET_KCAL, raw_target)

    # When the floor binds, the requested deficit is not the one applied — and
    # the gap is large (a 1100 kcal deficit becomes 5), so the reveal screen
    # would show three numbers that visibly fail to add up. Report what was
    # actually applied. Off the floor the requested figure is kept, because
    # "−550/day" is the meaningful number and the ≤5 kcal difference is just the
    # target being rounded to the nearest 10.
    floor_binds = raw_target < MIN_TARGET_KCAL
    applied_delta = target - rounded_tdee if floor_binds else _round_half_up(delta)

    gaining = goal_type is GoalType.GAIN
    protein_g, carbs_g, fat_g = _macros_for(target, metrics.weight_kg, gaining)

    if target_weight_kg is None:
        step = DEFAULT_TARGET_WEIGHT_DELTA_KG
        target_weight_kg = metrics.weight_kg + (step if gaining else -step)

    weeks = (
        0
        if goal_type is GoalType.MAINTAIN
        else max(
            1, _round_half_up(abs(target_weight_kg - metrics.weight_kg) / rate_kg_per_week)
        )
    )

    return TargetBreakdown(
        bmr=_round_half_up(bmr),
        activity_factor=factor,
        tdee=rounded_tdee,
        delta=applied_delta,
        target_calories=target,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        goal_type=goal_type,
        rate_kg_per_week=rate_kg_per_week,
        target_weight_kg=target_weight_kg,
        weeks_to_target=weeks,
    )
