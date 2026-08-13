"""Domain enumerations.

Every one of these is persisted as a plain ``String`` column rather than a
PostgreSQL ``ENUM``. Adding a member (a new auth provider, a new detection
method) then needs no migration at all — which is the whole point for
``AuthProvider``, where Apple and email sign-in are expected later.
"""

from enum import StrEnum


class AuthProvider(StrEnum):
    GOOGLE = "google"
    APPLE = "apple"
    EMAIL = "email"


class Sex(StrEnum):
    FEMALE = "female"
    MALE = "male"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    VERY = "very"
    EXTRA = "extra"


class GoalType(StrEnum):
    LOSE = "lose"
    MAINTAIN = "maintain"
    GAIN = "gain"


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


# Display order used by the day view. Snack sorts last regardless of when it was
# logged, matching the design.
MEAL_ORDER: dict[str, int] = {
    MealType.BREAKFAST: 0,
    MealType.LUNCH: 1,
    MealType.DINNER: 2,
    MealType.SNACK: 3,
}


def meal_sort_key(meal: str) -> int:
    return MEAL_ORDER.get(meal, len(MEAL_ORDER))


class DetectionMethod(StrEnum):
    PHOTO = "photo"
    TEXT = "text"
    BARCODE = "barcode"
    MANUAL = "manual"


class NutritionSource(StrEnum):
    USDA_FDC = "usda_fdc"
    OPEN_FOOD_FACTS = "open_food_facts"
    SEED = "seed"
    MANUAL = "manual"


class UnitPreference(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


class WeightSource(StrEnum):
    ONBOARDING = "onboarding"
    MANUAL = "manual"
