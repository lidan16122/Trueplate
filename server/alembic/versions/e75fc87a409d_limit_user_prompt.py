"""add users.max_prompts

Revision ID: e75fc87a409d
Revises: acac341a6d42
Create Date: 2026-09-03 18:39:32.806056

A lifetime cap on AI detections, per account.

Nullable with no server default, deliberately: null reads as *uncapped*, which
is the only safe thing for every row that exists when this runs. The model
carries a Python-side ``default=1``, so the cap applies from the next account
created onwards and never retroactively.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e75fc87a409d"
down_revision: str | Sequence[str] | None = "acac341a6d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("max_prompts", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "max_prompts")
