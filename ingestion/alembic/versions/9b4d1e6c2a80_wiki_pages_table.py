"""wiki_pages table (OKF knowledge bundle mirror)

Revision ID: 9b4d1e6c2a80
Revises: 7f3a1b2c4d5e
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa


revision = "9b4d1e6c2a80"
down_revision = "7f3a1b2c4d5e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wiki_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("entity_id", sa.Integer(),
                  sa.ForeignKey("entities.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("page", sa.String(), nullable=False),
        sa.Column("frontmatter", sa.JSON()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_wiki_pages_entity_id", "wiki_pages", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_wiki_pages_entity_id", table_name="wiki_pages")
    op.drop_table("wiki_pages")
