from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, NutritionPer100gMixin, TimestampMixin
from app.enums import NutritionSource


class BarcodeProduct(TimestampMixin, NutritionPer100gMixin, Base):
    """Postgres source of truth for UPC lookups.

    The UPC is the primary key rather than a surrogate UUID: it is genuinely
    unique, it is what the scanner produces, and it makes the Redis key
    (``barcode:{upc}``) map one-to-one onto the row it caches.

    Redis sits in *front* of this table, never in place of it — a cache miss
    falls through to here, and only a miss on both reaches Open Food Facts.
    """

    __tablename__ = "barcode_products"

    # GTIN-8/12/13/14 all fit; 32 leaves room for oddities without truncating.
    upc: Mapped[str] = mapped_column(String(32), primary_key=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Packaged products advertise per-serving figures. Those are normalised to
    # the per-100 g basis on the way in, so a scanned item and a photographed one
    # scale through identical code; this keeps the label's own serving for display.
    serving_size_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    serving_description: Mapped[str | None] = mapped_column(String(120), nullable=True)

    source: Mapped[str] = mapped_column(
        String(24), default=NutritionSource.OPEN_FOOD_FACTS, nullable=False
    )
    # Kept so a parsing change can be replayed against what the API actually
    # returned, without re-hitting a rate-limited upstream.
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
