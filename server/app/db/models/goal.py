import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class Goal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A calorie/macro target valid over a date range.

    Superseding a goal closes the old row (``ends_on``) and opens a new one
    rather than mutating in place, so a day logged against last month's target
    can still be judged against the target that was actually in force.

    The computed targets are snapshotted here on purpose: they are the numbers
    the user was held to. Recomputing them from today's profile would silently
    rewrite history the moment someone updates their weight.
    """

    __tablename__ = "goals"
    __table_args__ = (
        # At most one open goal per user. Partial, so closed history stays
        # unbounded. Named `ix_` rather than `uq_` because it is a unique *index*,
        # not a constraint — DROP CONSTRAINT will not find it.
        Index(
            "ix_goals_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("ends_on IS NULL"),
            # The same predicate for SQLite, which the tests run on. Without it
            # the index degrades to an unconditional one over user_id, and that
            # is not a weaker version of this rule — it is a different one that
            # forbids closed history, so superseding a goal raises where in
            # production it succeeds.
            sqlite_where=text("ends_on IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    goal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Magnitude in kg/week; direction comes from goal_type. The design has no
    # wizard step for this and defaults it to 0.5.
    target_rate_kg_per_week: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    target_calories: Mapped[int] = mapped_column(Integer, nullable=False)
    target_protein_g: Mapped[int] = mapped_column(Integer, nullable=False)
    target_carbs_g: Mapped[int] = mapped_column(Integer, nullable=False)
    target_fat_g: Mapped[int] = mapped_column(Integer, nullable=False)

    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    user: Mapped[User] = relationship(back_populates="goals")

    @property
    def is_active(self) -> bool:
        return self.ends_on is None
