"""The design prototype is the reference implementation for these numbers.

The target-reveal screen shows the user each intermediate step, so any drift
between this module and the design is something a user can see.
"""

from datetime import date

import pytest

from app.core.nutrition import (
    KCAL_PER_G_CARB,
    KCAL_PER_G_FAT,
    KCAL_PER_G_PROTEIN,
    BodyMetrics,
    _round_half_up,
    age_from_birth_date,
    basal_metabolic_rate,
    birth_date_from_age,
    calculate_targets,
)
from app.enums import ActivityLevel, GoalType, Sex

# The prototype's default state, reused wherever a concrete body is needed.
DESIGN_DEFAULT = BodyMetrics(weight_kg=74, height_cm=172, age=32, sex=Sex.FEMALE)


class TestDesignWorkedExample:
    """The prototype's default state: 32y female, 172 cm, 74 kg, losing 0.5 kg/wk."""

    @pytest.fixture
    def result(self):
        return calculate_targets(
            DESIGN_DEFAULT,
            goal_type=GoalType.LOSE,
            rate_kg_per_week=0.5,
            target_weight_kg=69,
        )

    def test_mifflin_st_jeor_matches_the_worked_example(self, result):
        # 10*74 + 6.25*172 - 5*32 = 1655; female subtracts 161.
        assert result.bmr == 1494

    def test_activity_factor_scales_bmr_to_maintenance(self, result):
        # 1494.0 * 1.375 = 2054.25
        assert result.tdee == 2054
        assert result.activity_factor == 1.375

    def test_half_a_kilo_a_week_becomes_a_550_kcal_deficit(self, result):
        # 0.5 kg/wk * 7700 kcal/kg / 7 days = 550 kcal/day deficit.
        assert result.delta == -550

    def test_target_rounds_to_nearest_ten(self, result):
        # 2054.25 - 550 = 1504.25 -> 1500
        assert result.target_calories == 1500

    def test_macro_grams_match_the_worked_example(self, result):
        assert result.protein_g == 133  # 74 * 1.8
        assert result.fat_g == 47  # 1500 * 0.28 / 9
        assert result.carbs_g == 136  # remainder / 4

    def test_macro_kcal_reconcile_to_target(self, result):
        total = result.protein_g * 4 + result.carbs_g * 4 + result.fat_g * 9
        # Integer gram rounding leaves a small residue; it must stay negligible.
        assert abs(total - result.target_calories) <= 4

    def test_timeline_is_distance_divided_by_rate(self, result):
        assert result.weeks_to_target == 10  # |69 - 74| / 0.5


class TestSex:
    def test_male_offset_is_plus_five(self):
        bmr = basal_metabolic_rate(BodyMetrics(weight_kg=80, height_cm=180, age=30, sex=Sex.MALE))
        assert bmr == pytest.approx(1780.0)

    def test_female_offset_is_minus_161(self):
        bmr = basal_metabolic_rate(BodyMetrics(weight_kg=80, height_cm=180, age=30, sex=Sex.FEMALE))
        assert bmr == pytest.approx(1614.0)

    def test_missing_sex_takes_the_midpoint_rather_than_assuming_one(self):
        def bmr_for(sex):
            return basal_metabolic_rate(
                BodyMetrics(weight_kg=80, height_cm=180, age=30, sex=sex)
            )

        male, female, unknown = bmr_for(Sex.MALE), bmr_for(Sex.FEMALE), bmr_for(None)
        assert unknown == pytest.approx((male + female) / 2)


class TestGoalTypes:
    def _calc(self, goal_type: GoalType, **kw):
        return calculate_targets(DESIGN_DEFAULT, goal_type=goal_type, **kw)

    def test_maintain_applies_no_delta(self):
        result = self._calc(GoalType.MAINTAIN)
        assert result.delta == 0
        assert result.target_calories == 2050  # 2054.25 -> nearest 10

    def test_maintain_reports_no_timeline(self):
        assert self._calc(GoalType.MAINTAIN).weeks_to_target == 0

    def test_gain_adds_a_surplus(self):
        result = self._calc(GoalType.GAIN, target_weight_kg=79)
        assert result.delta == 550
        assert result.target_calories > 2054

    def test_gain_raises_protein_and_lowers_fat_share(self):
        lose = self._calc(GoalType.LOSE, target_weight_kg=69)
        gain = self._calc(GoalType.GAIN, target_weight_kg=79)
        assert gain.protein_g == 163  # 74 * 2.2
        assert lose.protein_g == 133  # 74 * 1.8
        # 22% of calories from fat when gaining, 28% otherwise.
        assert gain.fat_g / gain.target_calories < lose.fat_g / lose.target_calories

    def test_target_weight_defaults_five_kg_in_the_goal_direction(self):
        assert self._calc(GoalType.LOSE).target_weight_kg == 69
        assert self._calc(GoalType.GAIN).target_weight_kg == 79


class TestFloor:
    def test_target_never_drops_below_1200(self):
        # A small, older person on an aggressive deficit would otherwise land
        # somewhere unsafe.
        result = calculate_targets(
            BodyMetrics(weight_kg=45, height_cm=150, age=70, sex=Sex.FEMALE),
            goal_type=GoalType.LOSE,
            rate_kg_per_week=1.0,
        )
        assert result.target_calories == 1200


class TestActivityLevel:
    def test_default_matches_the_designs_fixed_multiplier(self):
        assert (
            calculate_targets(DESIGN_DEFAULT, goal_type=GoalType.MAINTAIN).activity_factor
            == 1.375
        )

    def test_higher_activity_raises_the_target(self):
        sedentary = calculate_targets(
            DESIGN_DEFAULT, goal_type=GoalType.MAINTAIN, activity_level=ActivityLevel.SEDENTARY
        )
        very = calculate_targets(
            DESIGN_DEFAULT, goal_type=GoalType.MAINTAIN, activity_level=ActivityLevel.VERY
        )
        assert very.target_calories > sedentary.target_calories

    def test_unknown_level_falls_back_to_light(self):
        assert (
            calculate_targets(
                DESIGN_DEFAULT, goal_type=GoalType.MAINTAIN, activity_level="nonsense"
            ).activity_factor
            == 1.375
        )


class TestRoundHalfUp:
    def test_halves_round_up_not_to_even(self):
        # Python's built-in round() gives 2 and 4 here (banker's rounding),
        # which reads as a bug when two adjacent targets round opposite ways.
        assert _round_half_up(2.5) == 3
        assert _round_half_up(4.5) == 5
        # Halves go toward +infinity, so -2.5 rounds to -2 rather than -3. This
        # is also what JavaScript's Math.round does.
        assert _round_half_up(-2.5) == -2

    def test_ordinary_rounding_is_unchanged(self):
        assert _round_half_up(2.4) == 2
        assert _round_half_up(2.6) == 3


class TestAgeConversion:
    def test_age_survives_a_round_trip(self):
        today = date(2026, 8, 12)
        assert age_from_birth_date(birth_date_from_age(32, today), today) == 32

    def test_birthday_not_yet_reached_this_year(self):
        assert age_from_birth_date(date(1994, 12, 25), date(2026, 8, 12)) == 31

    def test_birthday_already_passed_this_year(self):
        assert age_from_birth_date(date(1994, 1, 5), date(2026, 8, 12)) == 32

    def test_leap_day_birth_date_does_not_raise(self):
        # 2024-02-29 minus 1 year has no 29 February to land on.
        assert birth_date_from_age(1, date(2024, 2, 29)) == date(2023, 2, 28)


class TestIncoherentGoals:
    """A rate of zero or below has no answer; it must not produce a target.

    Both were reachable from a stored row: `goals.target_rate_kg_per_week` is a
    non-null float with no positivity constraint.
    """

    def test_a_zero_rate_is_rejected_rather_than_dividing_by_zero(self):
        with pytest.raises(ValueError, match="positive rate"):
            calculate_targets(
                DESIGN_DEFAULT, goal_type=GoalType.LOSE, rate_kg_per_week=0
            )

    def test_a_negative_rate_is_rejected_rather_than_inverting_the_goal(self):
        # This previously returned a surplus for a weight-loss goal.
        with pytest.raises(ValueError, match="positive rate"):
            calculate_targets(
                DESIGN_DEFAULT, goal_type=GoalType.LOSE, rate_kg_per_week=-0.5
            )

    def test_maintain_ignores_the_rate_entirely(self):
        assert calculate_targets(
            DESIGN_DEFAULT, goal_type=GoalType.MAINTAIN, rate_kg_per_week=0
        ).delta == 0


class TestImpossibleBodies:
    """A half-filled profile must not silently produce a plausible-looking target."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [("weight_kg", 0), ("weight_kg", -5), ("height_cm", 0), ("age", 0), ("age", 200)],
    )
    def test_absurd_metrics_are_rejected(self, field, value):
        kwargs = {"weight_kg": 74, "height_cm": 172, "age": 32, **{field: value}}
        with pytest.raises(ValueError):
            BodyMetrics(**kwargs)


class TestMacrosAlwaysReconcile:
    """Protein and fat are derived independently, so they can exceed the target.

    Carbohydrate cannot absorb the excess by going negative. Before this was
    fixed, a heavy person on a steep deficit was shown macros summing to 24%
    more than the calorie target printed beside them.
    """

    @staticmethod
    def _kcal(result) -> int:
        return (
            result.protein_g * KCAL_PER_G_PROTEIN
            + result.carbs_g * KCAL_PER_G_CARB
            + result.fat_g * KCAL_PER_G_FAT
        )

    def test_macros_reconcile_when_protein_and_fat_alone_exceed_the_target(self):
        result = calculate_targets(
            BodyMetrics(weight_kg=160, height_cm=150, age=75, sex=Sex.FEMALE),
            goal_type=GoalType.LOSE,
            rate_kg_per_week=1.5,
            activity_level=ActivityLevel.SEDENTARY,
        )
        assert result.target_calories == 1200
        # Integer gram rounding across three macros leaves at most a few kcal.
        assert abs(self._kcal(result) - result.target_calories) <= 8

    @pytest.mark.parametrize("weight", [45, 74, 120, 200])
    @pytest.mark.parametrize("goal", [GoalType.LOSE, GoalType.GAIN, GoalType.MAINTAIN])
    def test_macros_reconcile_across_the_range(self, weight, goal):
        result = calculate_targets(
            BodyMetrics(weight_kg=weight, height_cm=165, age=40, sex=Sex.FEMALE),
            goal_type=goal,
            rate_kg_per_week=1.0,
        )
        assert abs(self._kcal(result) - result.target_calories) <= 8

    def test_the_floor_keeps_the_displayed_steps_adding_up(self):
        # tdee + delta must equal the target the user is shown, or the reveal
        # screen prints three numbers that visibly fail to reconcile.
        result = calculate_targets(
            BodyMetrics(weight_kg=45, height_cm=150, age=70, sex=Sex.FEMALE),
            goal_type=GoalType.LOSE,
            rate_kg_per_week=1.0,
        )
        assert result.target_calories == 1200
        assert result.tdee + result.delta == result.target_calories
