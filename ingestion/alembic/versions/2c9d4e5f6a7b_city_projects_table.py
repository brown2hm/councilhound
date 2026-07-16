"""city projects table

Revision ID: 2c9d4e5f6a7b
Revises: 860e70556e11
Create Date: 2026-07-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "2c9d4e5f6a7b"
down_revision = "860e70556e11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "city_projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_slug", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("project_type", sa.String(), nullable=True),
        sa.Column("division", sa.String(), nullable=True),
        sa.Column("official_status", sa.String(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requests", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("applicant", sa.Text(), nullable=True),
        sa.Column("planner_name", sa.Text(), nullable=True),
        sa.Column("planner_phone", sa.Text(), nullable=True),
        sa.Column("planner_email", sa.Text(), nullable=True),
        sa.Column("detail_url", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("documents", sa.JSON(), nullable=True),
        sa.Column("official_timeline", sa.JSON(), nullable=True),
        sa.Column("lat", sa.Numeric(), nullable=True),
        sa.Column("lng", sa.Numeric(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id"),
        sa.UniqueConstraint("external_slug"),
    )


def downgrade() -> None:
    op.drop_table("city_projects")
