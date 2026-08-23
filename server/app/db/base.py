import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. Without this, Alembic autogenerates unnamed
# indexes and constraints that a later migration has no handle to drop.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


def as_utc(value: datetime) -> datetime:
    """Force a timestamp read from the database into UTC-aware form.

    Postgres hands back an aware datetime for ``DateTime(timezone=True)``;
    SQLite, which the test suite runs on, hands back a naive one for the same
    column. Comparing the two raises, so every read of one of these columns
    normalises through here.

    It lives beside the columns rather than beside any one caller: it was
    written twice — once in the resolver, once in the detection cache — with
    near-identical comments, which is what a shared concern looks like just
    before it drifts.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class NutritionPer100gMixin:
    """The canonical nutrition basis: always per 100 g, never a total.

    Carried by every table that stores nutrition — ``foods``,
    ``barcode_products``, and the ``food_entries`` snapshot. Inheriting it makes
    the shared basis structural: a table that wants nutrition gets exactly these
    columns, so the three cannot drift apart one edit at a time, and a
    pre-multiplied total has nowhere to live.
    """

    kcal_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g_per_100g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    carbs_g_per_100g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fat_g_per_100g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fiber_g_per_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar_g_per_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sodium_mg_per_100g: Mapped[float | None] = mapped_column(Float, nullable=True)

    def scaled_to(self, grams: float) -> ScaledNutrition:
        """Resolve this per-100 g row to an actual portion."""
        factor = grams / 100.0
        return ScaledNutrition(
            calories=self.kcal_per_100g * factor,
            protein_g=self.protein_g_per_100g * factor,
            carbs_g=self.carbs_g_per_100g * factor,
            fat_g=self.fat_g_per_100g * factor,
        )


@dataclass(frozen=True, slots=True)
class ScaledNutrition:
    """A per-100 g row resolved against a gram quantity. Never persisted."""

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
