"""trigram index for transcript search

Revision ID: b8ff5ff92117
Revises: 18a917866dff
Create Date: 2026-07-14 06:19:34.244310

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision = 'b8ff5ff92117'
down_revision = '18a917866dff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # /search keyword matching uses plain ILIKE '%q%'; these GIN trigram
    # indexes make that an index scan instead of a full text sweep. The
    # embedded dev Postgres (pgserver) ships no contrib modules — there the
    # search simply runs unindexed, so skip rather than fail.
    available = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM pg_available_extensions WHERE name = 'pg_trgm'"
    )).scalar()
    if not available:
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcript_chunks_text_trgm "
        "ON transcript_chunks USING gin (lower(text) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agenda_items_title_trgm "
        "ON agenda_items USING gin (lower(coalesce(title, '')) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agenda_items_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_transcript_chunks_text_trgm")
    # pg_trgm extension stays; other objects may come to rely on it
