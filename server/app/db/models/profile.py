import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.enums import ActivityLevel, UnitPreference, WeightSource

if TYPE_CHECKING:
    from app.db.models.user import User


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The raw inputs a calorie target is derived from — never the target itself.

    Storing inputs rather than outputs means the formula can be swapped (a
    different BMR equation, a real activity multiplier) without invalidating a
    single day of history.
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    # The three BMR inputs are nullable because a profile row exists from the
    # moment onboarding starts, and the wizard fills them one step at a time. A
    # partially-filled profile therefore cannot produce a target — callers must
    # treat "no goal yet" as a real state rather than assume these are set.
    #
    # Weight is deliberately absent: it belongs in `weight_entries`, because it
    # moves and the progress chart needs the series, not the latest scalar.
    #
    # Birth date rather than age: an age integer is a snapshot that silently goes
    # stale, and every BMR formula wants current age. Onboarding collects age and
    # converts once, so this is an approximation until the user sets an exact date.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(16), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)

    # The onboarding wizard has no activity step — the design fixes the
    # multiplier at 1.375, which is exactly LIGHT. Kept as a real column so a
    # step can be added later without a migration.
    activity_level: Mapped[str] = mapped_column(
        String(24), default=ActivityLevel.LIGHT, nullable=False
    )

    unit_preference: Mapped[str] = mapped_column(
        String(8), default=UnitPreference.METRIC, nullable=False
    )
    # Required to know when a user's "today" starts; daily_logs is keyed on the
    # local date, not UTC. Captured silently from the browser at onboarding.
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")


class WeightEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Weight over time.

    A scalar on the profile could not support the trend chart, and weight is the
    one body metric that is expected to move. One entry per day; the onboarding
    answer becomes the first.
    """

    __tablename__ = "weight_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "recorded_on", name="uq_weight_entries_user_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recorded_on: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default=WeightSource.MANUAL, nullable=False)

    user: Mapped[User] = relationship(back_populates="weight_entries")
