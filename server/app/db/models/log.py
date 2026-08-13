import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    NutritionPer100gMixin,
    ScaledNutrition,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.enums import MealType, meal_sort_key

if TYPE_CHECKING:
    from app.db.models.user import User


class DailyLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One day of eating, keyed on the user's *local* date.

    Carries no cached totals — they are a SUM over entries. Caching them would
    buy nothing on a query this small and would introduce a value that can drift
    out of agreement with the rows it summarises.
    """

    __tablename__ = "daily_logs"
    __table_args__ = (UniqueConstraint("user_id", "log_date", name="uq_daily_logs_user_date"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="daily_logs")
    entries: Mapped[list[FoodEntry]] = relationship(
        back_populates="daily_log",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def grouped_by_meal(self) -> list[tuple[str, list[FoodEntry]]]:
        """Entries bucketed into meals, in the design's fixed display order."""
        buckets: dict[str, list[FoodEntry]] = {}
        for entry in self.entries:
            buckets.setdefault(entry.meal_type, []).append(entry)
        return sorted(buckets.items(), key=lambda kv: meal_sort_key(kv[0]))


class FoodEntry(UUIDPrimaryKeyMixin, TimestampMixin, NutritionPer100gMixin, Base):
    """One eaten item.

    Nutrition is stored **per 100 g** alongside the portion in grams, rather than
    as a pre-multiplied total. That is the same basis the whole app uses, and it
    means correcting a portion is a single-field edit that recomputes exactly —
    no stale totals, no re-fetch of the source food.

    The per-100 g values are a *snapshot*, not a foreign key: if USDA later
    revises an entry, days already logged keep the numbers they were logged with.
    """

    __tablename__ = "food_entries"

    daily_log_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("daily_logs.id", ondelete="CASCADE"), index=True, nullable=False
    )

    meal_type: Mapped[str] = mapped_column(String(16), default=MealType.SNACK, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)

    quantity_g: Mapped[float] = mapped_column(Float, nullable=False)
    serving_description: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- provenance ---
    detection_method: Mapped[str] = mapped_column(String(16), nullable=False)
    nutrition_source: Mapped[str] = mapped_column(String(24), nullable=False)
    # Upstream identifier for this row, read according to `nutrition_source`: an
    # FDC id for USDA, a UPC for a barcode, null for a manual entry. Deliberately
    # one nullable column rather than three — the source already says how to read
    # it, and three mutually exclusive columns would need the same switch anyway.
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 0..1. Null for barcode and manual entries, which are not estimates.
    detection_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Ties an entry back to the photo it came from, and to the AI cache key.
    image_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    logged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    daily_log: Mapped[DailyLog] = relationship(back_populates="entries")

    # --- resolved totals for this portion ---
    # Derived, never stored: correcting the portion is a single-field edit to
    # `quantity_g` and every total follows.
    @property
    def resolved(self) -> ScaledNutrition:
        return self.scaled_to(self.quantity_g)

    @property
    def calories(self) -> float:
        return self.resolved.calories

    @property
    def protein_g(self) -> float:
        return self.resolved.protein_g

    @property
    def carbs_g(self) -> float:
        return self.resolved.carbs_g

    @property
    def fat_g(self) -> float:
        return self.resolved.fat_g
