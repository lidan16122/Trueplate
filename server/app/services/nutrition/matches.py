"""Building a ``NutritionMatch``, and deciding when its figures are usable.

The sibling of ``relevance.py``: that one asks whether a row is about the right
*food*, this one whether its *numbers* can describe food at all. Both exist
because every upstream here answers confidently and none of them validate.

Neutral ground on purpose. ``barcode.py`` and ``resolver.py`` both turn a
``barcode_products`` row into a match, and neither can import the other —
``barcode`` imports the ``nutrition`` package, which imports ``resolver``, so
the reverse edge would close a cycle.
"""

from app.db.models.barcode import BarcodeProduct
from app.db.models.food import Food
from app.schemas.detection import NutritionMatch

# Kilojoules per kilocalorie. Some upstream rows publish only kJ.
KJ_PER_KCAL = 4.184

# Pure fat is about 900 kcal per 100 g, and nothing edible beats it. A row above
# this is a unit error rather than a rich food — kJ written into the kcal field
# is the usual one, and it arrives looking like an ordinary number.
#
# It matters beyond taste: `FoodEntryCreate` caps `kcal_per_100g` at 1000 and
# each macro at 100, and the save is one request carrying every item. A single
# out-of-range row therefore 422s the *whole meal*, after the user has already
# corrected the portions. Rejecting here instead lets the resolver widen to the
# next rung and find something real.
MAX_KCAL_PER_100G = 900.0
MAX_MACRO_G_PER_100G = 100.0


def kcal_from(kcal: float | None, kj: float | None) -> float | None:
    """Energy in kcal, converting from kJ only when that is all there is.

    Deriving kcal from a published kJ figure is arithmetic on a sourced number,
    not an estimate, so provenance survives it. ``None`` means the row carries no
    energy at all, which makes it unusable — better to fall through to the next
    rung than to render a food at 0 kcal that looks resolved.
    """
    if kcal is not None:
        return kcal
    if kj is not None:
        return kj / KJ_PER_KCAL
    return None


def is_plausible(match: NutritionMatch) -> bool:
    """Whether these figures could describe a real food, per 100 g."""
    macros = (match.protein_g_per_100g, match.carbs_g_per_100g, match.fat_g_per_100g)
    return 0 <= match.kcal_per_100g <= MAX_KCAL_PER_100G and all(
        0 <= grams <= MAX_MACRO_G_PER_100G for grams in macros
    )


def from_food_row(row: Food) -> NutritionMatch:
    """A curated or previously fetched ``foods`` row."""
    return NutritionMatch(
        food_id=str(row.id),
        name=row.name,
        brand=row.brand,
        source=row.source,
        source_ref=row.source_ref,
        kcal_per_100g=row.kcal_per_100g,
        protein_g_per_100g=row.protein_g_per_100g,
        carbs_g_per_100g=row.carbs_g_per_100g,
        fat_g_per_100g=row.fat_g_per_100g,
    )


def from_barcode_product(row: BarcodeProduct) -> NutritionMatch:
    """A product previously resolved through an exact UPC.

    ``source_ref`` is the barcode itself, which is what lets a figure shown to
    the user be traced back to the scan that produced it.
    """
    return NutritionMatch(
        name=row.name,
        brand=row.brand,
        source=row.source,
        source_ref=row.upc,
        serving_description=row.serving_description,
        kcal_per_100g=row.kcal_per_100g,
        protein_g_per_100g=row.protein_g_per_100g,
        carbs_g_per_100g=row.carbs_g_per_100g,
        fat_g_per_100g=row.fat_g_per_100g,
    )
