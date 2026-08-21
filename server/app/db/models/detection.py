from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Detection(Base, TimestampMixin):
    """Content-addressed cache of a completed detection.

    Re-submitting the same photo must not pay for a second vision call — that is
    the single most expensive thing this app does, and a user who retries after a
    dropped connection would otherwise be billed twice for one meal. The
    ``cached`` flag on ``FoodDetectionResponse`` exists to surface exactly this.

    In Postgres rather than Redis, deliberately. Redis here is reserved for
    refresh-token families and rate-limit counters; a detection payload is
    comparatively large, long-lived, and perfectly happy as a single-key
    Postgres read.

    Keyed by content, not by user: two people photographing the same packaged
    item get the same answer, and there is nothing user-identifying in the row
    to leak by sharing it. ``food_entries.image_hash`` cannot serve this — it
    only covers meals that were actually *logged*, and the point is to avoid
    re-paying for a detection the user abandoned before confirming.
    """

    __tablename__ = "detections"

    # sha256 hex of the image bytes, or of the normalised description for the
    # text path. Fixed width, so the PK index stays small.
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    # The whole FoodDetectionResponse, stored as it was served. JSON rather than
    # columns because it is only ever read back whole and handed to the client —
    # normalising it would buy nothing and couple the cache to the schema's shape.
    #
    # The SQLite variant is what lets the test suite exercise this table without
    # a running Postgres; JSONB has no SQLite equivalent.
    payload: Mapped[dict] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
