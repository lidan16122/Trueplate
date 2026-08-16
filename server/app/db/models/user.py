import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.goal import Goal
    from app.db.models.log import DailyLog
    from app.db.models.profile import UserProfile, WeightEntry


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person. Deliberately holds no credential of any kind.

    Identity is separated from provider so Apple or email sign-in can be added
    by inserting an ``AuthIdentity`` row — no migration, no reshaping of users.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    # Split rather than a single display_name: the profile screen edits the two
    # independently, and the avatar badge is built from both initials.
    first_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    identities: Mapped[list[AuthIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    goals: Mapped[list[Goal]] = relationship(back_populates="user", cascade="all, delete-orphan")
    weight_entries: Mapped[list[WeightEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    daily_logs: Mapped[list[DailyLog]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def initials(self) -> str:
        first = self.first_name[:1].upper() if self.first_name else ""
        last = self.last_name[:1].upper() if self.last_name else ""
        return (first + last) or (self.email[:1].upper() if self.email else "?")


class AuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One sign-in method belonging to a user.

    ``(provider, provider_user_id)`` is the natural key the login flow upserts
    against — never the email, which a user can change at the provider.
    """

    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_auth_identities_provider_subject"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Email as the provider reported it, which may drift from users.email.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="identities")
