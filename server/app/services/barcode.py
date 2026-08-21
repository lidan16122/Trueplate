"""Barcode decoding and UPC lookup.

Decoding happens server-side: the client uploads the photo it already has, and
no JS barcode library ships to the browser. That also means the desktop path —
where the design asks the user to *type* the number — reaches exactly the same
code with the decode step skipped.

Lookup order is ``barcode_products`` then Open Food Facts, then write back.
There is no Redis layer; see ``services/detection_cache.py`` for why.
"""

import io
import logging
import re
import uuid
from datetime import UTC, datetime

from PIL import Image, ImageOps
from pyzbar import pyzbar
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.barcode import BarcodeProduct
from app.enums import DetectionMethod, MealType, NutritionSource
from app.schemas.detection import (
    DetectedFood,
    FoodDetectionResponse,
    NutritionFacts,
    NutritionMatch,
    ResolvedFoodItem,
)
from app.services.nutrition import OpenFoodFactsClient

logger = logging.getLogger(__name__)

_DIGITS = re.compile(r"^\d{8,14}$")

# Retail product symbologies only. Leaving QR out is deliberate: a QR code on
# packaging is a marketing URL, and decoding one would send a website into a UPC
# lookup that can only ever miss.
_SYMBOLS = [
    pyzbar.ZBarSymbol.EAN13,
    pyzbar.ZBarSymbol.EAN8,
    pyzbar.ZBarSymbol.UPCA,
    pyzbar.ZBarSymbol.UPCE,
]


class BarcodeError(Exception):
    """Base for barcode failures the route turns into a status code."""


class BarcodeUnreadable(BarcodeError):
    """No barcode found in the image. Maps to 422."""


class BarcodeNotFood(BarcodeError):
    """Decoded fine, but the product is unknown or is not a food. Maps to 422."""


def decode(data: bytes) -> str | None:
    """Read the first retail barcode in an image, or None.

    Deliberately given the **original** upload rather than the downscaled copy
    the vision call uses: a barcode occupies a small part of a packaging photo,
    and resizing to 1568 px routinely destroys the bar widths that carry the
    signal.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            # zbar reads intensity, and greyscale converts once instead of per
            # scan line. Also sidesteps palette and alpha modes entirely.
            results = pyzbar.decode(image.convert("L"), symbols=_SYMBOLS)
    except (OSError, ValueError) as exc:
        logger.info("Barcode decode failed: %s", exc)
        return None

    for result in results:
        code = result.data.decode("ascii", errors="ignore").strip()
        if _DIGITS.match(code):
            return code
    return None


def normalize(code: str) -> list[str]:
    """Candidate keys to try for one scanned code, most likely first.

    A 12-digit UPC-A and its 13-digit EAN form differ only by a leading zero,
    and Open Food Facts is inconsistent about which it files a product under —
    so a lookup that tries only what the scanner produced misses real products.
    """
    code = code.strip()
    candidates = [code]
    if len(code) == 12:
        candidates.append("0" + code)
    elif len(code) == 13 and code.startswith("0"):
        candidates.append(code[1:])
    return candidates


def _match_from_row(row: BarcodeProduct) -> NutritionMatch:
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


async def lookup(
    db: AsyncSession, off: OpenFoodFactsClient, code: str
) -> tuple[NutritionMatch, float, str | None]:
    """Resolve a UPC to a match, a default portion in grams, and its label.

    Raises ``BarcodeNotFood`` when the code is unknown or the product carries no
    usable nutrition — a barcode for shampoo is a typed refusal, not a plate.
    """
    candidates = normalize(code)

    for candidate in candidates:
        row = await db.get(BarcodeProduct, candidate)
        if row is not None:
            grams = row.serving_size_g or 100.0
            return _match_from_row(row), grams, row.serving_description

    for candidate in candidates:
        found = await off.product(candidate)
        if found is None:
            continue

        # Write back so the next scan of this product is a single Postgres read.
        # Barcodes are the one lookup where the key is exact, so unlike a
        # name search there is nothing to be uncertain about.
        row = BarcodeProduct(
            upc=candidate,
            name=found.match.name,
            brand=found.match.brand,
            serving_size_g=found.serving_size_g,
            serving_description=found.serving_description,
            source=NutritionSource.OPEN_FOOD_FACTS,
            raw_payload=found.raw_payload,
            fetched_at=datetime.now(UTC),
            kcal_per_100g=found.match.kcal_per_100g,
            protein_g_per_100g=found.match.protein_g_per_100g,
            carbs_g_per_100g=found.match.carbs_g_per_100g,
            fat_g_per_100g=found.match.fat_g_per_100g,
        )
        try:
            # A SAVEPOINT rather than the request's whole transaction — the
            # route commits this same session afterwards, and a bare rollback
            # would leave it committing a dead session.
            async with db.begin_nested():
                db.add(row)
        except IntegrityError:
            # Another request cached the same UPC first; theirs is the same
            # product, so there is nothing to reconcile.
            pass

        grams = found.serving_size_g or 100.0
        # The OFF client builds the match without a serving — that field only
        # means anything on the barcode path — so attach it here, where the
        # product's own label is in hand.
        match = found.match.model_copy(
            update={"serving_description": found.serving_description}
        )
        return match, grams, found.serving_description

    raise BarcodeNotFood(
        "That barcode is not a food we can find. It may be a non-food product, "
        "or simply not in the database yet."
    )


def to_response(
    match: NutritionMatch,
    grams: float,
    serving_description: str | None,
    meal_type: MealType | None,
) -> FoodDetectionResponse:
    """Shape a barcode hit like every other detection.

    Every path ends at the same ``FoodDetectionResponse`` so the confirmation
    screen needs no idea which one produced it.
    """
    nutrition = NutritionFacts.for_portion(match, grams)
    detected = DetectedFood(
        label=match.name,
        estimated_grams=grams,
        # An exact key against a label the manufacturer printed. Nothing was
        # estimated, so nothing should be flagged for correction.
        confidence=1.0,
        preparation="unknown",
        search_terms=[match.name],
        portion_reasoning=(
            f"One serving ({serving_description})" if serving_description else "Per 100 g"
        ),
    )
    return FoodDetectionResponse(
        detection_id=str(uuid.uuid4()),
        kind=DetectionMethod.BARCODE,
        source_label="Scanned · packaged product",
        meal_type=meal_type or MealType.SNACK,
        items=[
            ResolvedFoodItem(
                detected=detected,
                matched=match,
                nutrition=nutrition,
                alternatives=[],
                confidence_label="Fairly sure",
                is_rough=False,
            )
        ],
        totals=nutrition,
        cached=False,
    )
