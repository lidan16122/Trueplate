from datetime import datetime

from sqlalchemy import DateTime, Index, String, text
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
    )

    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source: Mapped[str] = mapped_column(String(24), default=NutritionSource.SEED, nullable=False)
    # FDC id for USDA rows; null for seeded rows.
    source_ref: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
