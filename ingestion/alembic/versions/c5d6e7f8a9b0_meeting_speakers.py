"""meeting_speakers: who each diarization label is, per meeting

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-10-04 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'c5d6e7f8a9b0'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'meeting_speakers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('meeting_id', sa.Integer(),
                  sa.ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('speaker_label', sa.String(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('entity_id', sa.Integer(),
                  sa.ForeignKey('entities.id', ondelete='SET NULL'), nullable=True),
        sa.Column('role', sa.String(), nullable=True),
        sa.Column('confidence', sa.String(), nullable=False),
        sa.Column('mixed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='model'),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('meeting_id', 'speaker_label'),
    )
    op.create_index('ix_meeting_speakers_meeting_id', 'meeting_speakers', ['meeting_id'])


def downgrade() -> None:
    op.drop_index('ix_meeting_speakers_meeting_id', table_name='meeting_speakers')
    op.drop_table('meeting_speakers')
