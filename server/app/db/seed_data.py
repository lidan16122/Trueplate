"""Reference foods used for local development.

Lifted from the design prototype's ``FOODS`` map so the day view renders real
numbers before the USDA FoodData Central integration lands. Every value is per
100 g — the same basis every other nutrition column in this app uses.

These are development figures, not verified against USDA. Rows seeded from here
are tagged ``NutritionSource.SEED`` so they stay distinguishable from real data.
"""

from typing import NamedTuple


class SeedNutrition(NamedTuple):
    """Per-100 g figures for one seed food.

    Named rather than a bare 4-tuple so the field order lives here once, instead
    of being re-asserted by every unpacking site.
    """

    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float


SEED_FOODS: dict[str, SeedNutrition] = {
    "Greek yoghurt": SeedNutrition(59, 10, 3.6, 0.4),
    "Blueberries": SeedNutrition(57, 0.7, 14, 0.3),
    "Rolled oats": SeedNutrition(379, 13, 67, 7),
    "Honey": SeedNutrition(304, 0.3, 82, 0),
    "Grilled chicken breast": SeedNutrition(165, 31, 0, 3.6),
    "Jasmine rice, cooked": SeedNutrition(130, 2.7, 28, 0.3),
    "Roasted broccoli": SeedNutrition(55, 3.7, 7, 1.5),
    "Olive oil": SeedNutrition(884, 0, 0, 100),
    "Salmon fillet": SeedNutrition(208, 20, 0, 13),
    "Sourdough bread": SeedNutrition(270, 11, 48, 2),
    "Avocado": SeedNutrition(160, 2, 9, 15),
    "Flat white": SeedNutrition(55, 3.2, 4.6, 2.6),
    "Almonds": SeedNutrition(579, 21, 22, 50),
    "Banana": SeedNutrition(89, 1.1, 23, 0.3),
    "Protein bar": SeedNutrition(350, 30, 34, 10),
}
