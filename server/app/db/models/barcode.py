from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, NutritionPer100gMixin, TimestampMixin
from app.enums import NutritionSource


class BarcodeProduct(TimestampMixin, NutritionPer100gMixin, Base):
    """Postgres source of truth for UPC lookups.

    The UPC is the primary key rather than a surrogate UUID: it is genuinely
    unique, and it is what the scanner produces.

    Lookup order is this table, then Open Food Facts on a miss, then write back.
    There is deliberately no Redis layer in front: the Upstash instance is small
    and reserved for refresh-token families and rate-limit counters, and a
    barcode row is a single-key Postgres read that caching would only buy an
    invalidation problem for. This is the same call CLAUDE.md records for
    profiles, goals and day totals.
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
    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
