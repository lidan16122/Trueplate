"""Initial schema: users, auth, profile, goals, logs, food reference

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- reference data (no FKs) ---
    op.create_table(
        "barcode_products",
        sa.Column("upc", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("serving_size_g", sa.Float(), nullable=True),
        sa.Column("serving_description", sa.String(length=120), nullable=True),
        sa.Column("kcal_per_100g", sa.Float(), nullable=False),
        sa.Column("protein_g_per_100g", sa.Float(), nullable=False),
        sa.Column("carbs_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fat_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fiber_g_per_100g", sa.Float(), nullable=True),
        sa.Column("sugar_g_per_100g", sa.Float(), nullable=True),
        sa.Column("sodium_mg_per_100g", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("upc", name=op.f("pk_barcode_products")),
    )

    op.create_table(
        "foods",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("kcal_per_100g", sa.Float(), nullable=False),
        sa.Column("protein_g_per_100g", sa.Float(), nullable=False),
        sa.Column("carbs_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fat_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fiber_g_per_100g", sa.Float(), nullable=True),
        sa.Column("sugar_g_per_100g", sa.Float(), nullable=True),
        sa.Column("sodium_mg_per_100g", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_foods")),
    )
    op.create_index(op.f("ix_foods_name"), "foods", ["name"], unique=False)
    op.create_index(
        "ix_foods_name_lower", "foods", [sa.literal_column("lower(name)")], unique=False
    )
    op.create_index(op.f("ix_foods_source_ref"), "foods", ["source_ref"], unique=False)

    # --- identity ---
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "auth_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_auth_identities_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_identities")),
        sa.UniqueConstraint(
            "provider", "provider_user_id", name="uq_auth_identities_provider_subject"
        ),
    )
    op.create_index(
        op.f("ix_auth_identities_user_id"), "auth_identities", ["user_id"], unique=False
    )

    # --- profile / goals ---
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.String(length=16), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("activity_level", sa.String(length=24), nullable=False),
        sa.Column("unit_preference", sa.String(length=8), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_user_profiles_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profiles")),
    )
    op.create_index(op.f("ix_user_profiles_user_id"), "user_profiles", ["user_id"], unique=True)

    op.create_table(
        "weight_entries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_on", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_weight_entries_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weight_entries")),
        sa.UniqueConstraint("user_id", "recorded_on", name="uq_weight_entries_user_date"),
    )
    op.create_index(op.f("ix_weight_entries_user_id"), "weight_entries", ["user_id"], unique=False)

    op.create_table(
        "goals",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_type", sa.String(length=16), nullable=False),
        sa.Column("target_weight_kg", sa.Float(), nullable=True),
        sa.Column("target_rate_kg_per_week", sa.Float(), nullable=False),
        sa.Column("target_calories", sa.Integer(), nullable=False),
        sa.Column("target_protein_g", sa.Integer(), nullable=False),
        sa.Column("target_carbs_g", sa.Integer(), nullable=False),
        sa.Column("target_fat_g", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_goals_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goals")),
    )
    op.create_index(op.f("ix_goals_user_id"), "goals", ["user_id"], unique=False)
    # Partial: at most one open goal per user, while closed history stays unbounded.
    op.create_index(
        "ix_goals_user_active",
        "goals",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ends_on IS NULL"),
    )

    # --- the log ---
    op.create_table(
        "daily_logs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_daily_logs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_logs")),
        sa.UniqueConstraint("user_id", "log_date", name="uq_daily_logs_user_date"),
    )
    op.create_index(op.f("ix_daily_logs_user_id"), "daily_logs", ["user_id"], unique=False)

    op.create_table(
        "food_entries",
        sa.Column("daily_log_id", sa.Uuid(), nullable=False),
        sa.Column("meal_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("quantity_g", sa.Float(), nullable=False),
        sa.Column("serving_description", sa.String(length=120), nullable=True),
        sa.Column("kcal_per_100g", sa.Float(), nullable=False),
        sa.Column("protein_g_per_100g", sa.Float(), nullable=False),
        sa.Column("carbs_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fat_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fiber_g_per_100g", sa.Float(), nullable=True),
        sa.Column("sugar_g_per_100g", sa.Float(), nullable=True),
        sa.Column("sodium_mg_per_100g", sa.Float(), nullable=True),
        sa.Column("detection_method", sa.String(length=16), nullable=False),
        sa.Column("nutrition_source", sa.String(length=24), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column("detection_confidence", sa.Float(), nullable=True),
        sa.Column("image_hash", sa.String(length=64), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["daily_log_id"], ["daily_logs.id"],
            name=op.f("fk_food_entries_daily_log_id_daily_logs"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food_entries")),
    )
    op.create_index(
        op.f("ix_food_entries_daily_log_id"), "food_entries", ["daily_log_id"], unique=False
    )
    op.create_index(op.f("ix_food_entries_image_hash"), "food_entries", ["image_hash"], unique=False)


def downgrade() -> None:
    # Reverse dependency order. Indexes on a dropped table go with it, so only
    # the tables need naming here.
    op.drop_table("food_entries")
    op.drop_table("daily_logs")
    op.drop_table("goals")
    op.drop_table("weight_entries")
    op.drop_table("user_profiles")
    op.drop_table("auth_identities")
    op.drop_table("users")
    op.drop_table("foods")
    op.drop_table("barcode_products")
