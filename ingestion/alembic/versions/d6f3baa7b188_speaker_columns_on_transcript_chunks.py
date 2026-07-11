"""speaker columns on transcript_chunks

Revision ID: d6f3baa7b188
Revises: abf2688b3a53
Create Date: 2026-07-11 17:18:04.622012

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision = 'd6f3baa7b188'
down_revision = 'abf2688b3a53'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('transcript_chunks', sa.Column('speaker_label', sa.String(), nullable=True))
    op.add_column('transcript_chunks', sa.Column('speaker_entity_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_transcript_chunks_speaker_entity_id',
        'transcript_chunks', 'entities', ['speaker_entity_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_transcript_chunks_speaker_entity_id', 'transcript_chunks', type_='foreignkey')
    op.drop_column('transcript_chunks', 'speaker_entity_id')
    op.drop_column('transcript_chunks', 'speaker_label')
