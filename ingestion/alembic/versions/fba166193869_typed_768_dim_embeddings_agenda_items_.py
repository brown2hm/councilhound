"""typed 768-dim embeddings, agenda_items embedding

Revision ID: fba166193869
Revises: e1a2b3c4d5f6
Create Date: 2026-07-11 22:51:23.348302

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision = 'fba166193869'
down_revision = 'e1a2b3c4d5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('agenda_items', sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True))
    # autogenerate can't see dimension changes: untyped vector -> vector(768)
    # (column is all-NULL at this point, so no data conversion involved)
    op.execute("ALTER TABLE transcript_chunks ALTER COLUMN embedding TYPE vector(768)")
    op.execute("CREATE INDEX ix_transcript_chunks_embedding ON transcript_chunks "
               "USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX ix_agenda_items_embedding ON agenda_items "
               "USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcript_chunks_embedding")
    op.execute("DROP INDEX IF EXISTS ix_agenda_items_embedding")
    op.execute("ALTER TABLE transcript_chunks ALTER COLUMN embedding TYPE vector")
    op.drop_column('agenda_items', 'embedding')
