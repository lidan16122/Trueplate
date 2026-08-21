from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, NutritionPer100gMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.enums import NutritionSource


class Food(UUIDPrimaryKeyMixin, TimestampMixin, NutritionPer100gMixin, Base):
    """Generic nutrition reference, looked up by name.

    Separate from ``barcode_products`` because the two are reached by different
    keys from different upstreams: this one is searched by name against USDA
    FoodData Central, that one is fetched by UPC from Open Food Facts. Collapsing
    them would leave a table half of whose rows have no usable primary lookup key.
    """

    __tablename__ = "foods"
    __table_args__ = (
        # Case-insensitive name lookup — the shape every "find me a food called
        # X" query takes, whether it comes from AI search terms or a text log.
        Index("ix_foods_name_lower", text("lower(name)")),
        # What makes write-back converge instead of accumulating near-duplicates.
        # The resolver stores a food under the canonical search term that
        # resolved it, so without this two concurrent detections of the same term
        # each insert a row and every later lookup has to arbitrate between them.
        # Scoped by source as well as name because the same term legitimately
        # resolves differently against USDA and Open Food Facts, and a curated
        # seed row must be able to coexist with a fetched one.
        UniqueConstraint("name", "source", name="uq_foods_name_source"),
    )

    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source: Mapped[str] = mapped_column(String(24), default=NutritionSource.SEED, nullable=False)
    # FDC id for USDA rows; null for seeded rows.
    source_ref: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    # The SQLite variant is only for the test suite, which has no JSONB. It
    # changes nothing about the Postgres column.
    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
