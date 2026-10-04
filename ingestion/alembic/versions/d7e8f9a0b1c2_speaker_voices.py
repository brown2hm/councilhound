"""speaker_voices: a voice fingerprint per diarization label

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-10-04 18:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = 'd7e8f9a0b1c2'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'speaker_voices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('meeting_id', sa.Integer(),
                  sa.ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('speaker_label', sa.String(), nullable=False),
        sa.Column('embedding', Vector(256), nullable=False),
        sa.Column('speech_seconds', sa.Numeric(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('meeting_id', 'speaker_label'),
    )
    op.create_index('ix_speaker_voices_meeting_id', 'speaker_voices', ['meeting_id'])


def downgrade() -> None:
    op.drop_index('ix_speaker_voices_meeting_id', table_name='speaker_voices')
    op.drop_table('speaker_voices')
