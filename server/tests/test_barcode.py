"""Barcode decoding and UPC resolution.

The decode test renders a real EAN-13 and reads it back, because the thing worth
proving is that zbar works on this platform at all — pyzbar was chosen over
zxing-cpp specifically because zxing-cpp publishes no wheels for Python 3.14,
and a ctypes shim with bundled DLLs is exactly the kind of dependency that
imports fine and then does nothing.
"""

import io

import barcode
import httpx
import pytest
from barcode.writer import ImageWriter
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.barcode import BarcodeProduct
from app.services import barcode as barcode_service
from app.services.nutrition import OpenFoodFactsClient
from tests.fakes import nutrition_transport, off_product_payload

EAN13 = "5000112637939"


def render_barcode(code: str = EAN13) -> bytes:
    buffer = io.BytesIO()
    barcode.get("ean13", code[:12], writer=ImageWriter()).write(buffer)
    return buffer.getvalue()


def test_a_rendered_barcode_decodes_back_to_its_digits() -> None:
    decoded = barcode_service.decode(render_barcode())
    assert decoded is not None
    # python-barcode recomputes the checksum from the first 12 digits, so
    # compare on those rather than assuming our constant's check digit.
    assert decoded[:12] == EAN13[:12]


def test_a_photo_with_no_barcode_decodes_to_nothing() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), (120, 90, 60)).save(buffer, format="JPEG")
    assert barcode_service.decode(buffer.getvalue()) is None


def test_unreadable_bytes_do_not_raise() -> None:
    """A truncated upload is a 422 for the user, not a 500."""
    assert barcode_service.decode(b"not an image at all") is None


def test_upc_a_and_ean_13_forms_are_both_tried() -> None:
    """Open Food Facts files the same product under either, inconsistently."""
    assert barcode_service.normalize("012345678905") == ["012345678905", "0012345678905"]
    assert barcode_service.normalize("0012345678905") == ["0012345678905", "012345678905"]


async def test_known_product_is_served_from_postgres_without_calling_off(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        BarcodeProduct(
            upc=EAN13,
            name="Test Bar",
            brand="Testco",
            serving_size_g=40.0,
            serving_description="1 bar (40 g)",
            kcal_per_100g=400.0,
            protein_g_per_100g=20.0,
            carbs_g_per_100g=40.0,
            fat_g_per_100g=15.0,
        )
    )
    await db_session.flush()

    # A transport that would 404 everything: reaching it at all is the failure.
    off = OpenFoodFactsClient(httpx.AsyncClient(transport=nutrition_transport()))
    match, grams, serving = await barcode_service.lookup(db_session, off, EAN13)

    assert match.name == "Test Bar"
    assert grams == 40.0
    assert serving == "1 bar (40 g)"


async def test_unknown_product_is_fetched_and_written_back(db_session: AsyncSession) -> None:
    transport = nutrition_transport(off_product=off_product_payload("Choco Bar", 450.0, EAN13))
    off = OpenFoodFactsClient(httpx.AsyncClient(transport=transport))

    match, grams, _ = await barcode_service.lookup(db_session, off, EAN13)
    assert match.name == "Choco Bar"
    assert grams == 30.0

    # Written back, so the next scan is a single Postgres read.
    stored = await db_session.get(BarcodeProduct, EAN13)
    assert stored is not None
    assert stored.kcal_per_100g == 450.0


async def test_a_non_food_barcode_is_refused_not_invented(db_session: AsyncSession) -> None:
    """Shampoo is not in Open Food Facts; that must be a typed error."""
    off = OpenFoodFactsClient(httpx.AsyncClient(transport=nutrition_transport()))

    with pytest.raises(barcode_service.BarcodeNotFood):
        await barcode_service.lookup(db_session, off, "9999999999999")


async def test_a_barcode_hit_is_never_flagged_as_a_rough_guess(
    db_session: AsyncSession,
) -> None:
    """An exact key against a printed label is not an estimate."""
    transport = nutrition_transport(off_product=off_product_payload("Choco Bar", 450.0, EAN13))
    off = OpenFoodFactsClient(httpx.AsyncClient(transport=transport))

    match, grams, serving = await barcode_service.lookup(db_session, off, EAN13)
    response = barcode_service.to_response(match, grams, serving, None)

    assert response.rough_count == 0
    assert response.items[0].confidence_label == "Fairly sure"
    # 450 kcal/100 g at a 30 g serving.
    assert response.totals.calories == pytest.approx(135.0)
