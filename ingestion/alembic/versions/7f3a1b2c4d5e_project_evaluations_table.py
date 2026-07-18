"""project evaluations table

Revision ID: 7f3a1b2c4d5e
Revises: 2c9d4e5f6a7b
Create Date: 2026-07-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "7f3a1b2c4d5e"
down_revision = "2c9d4e5f6a7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("extraction_model", sa.String(), nullable=True),
        sa.Column("extraction_prompt_version", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("module_results", sa.JSON(), nullable=True),
        sa.Column("map_layers", sa.JSON(), nullable=True),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("report_markdown", sa.Text(), nullable=True),
        sa.Column("report_model", sa.String(), nullable=True),
        sa.Column("report_prompt_version", sa.String(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synthesized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["city_project_id"], ["city_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("city_project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_evaluations")
