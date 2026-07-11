"""repair indexes and fk name

An earlier autogenerate dropped the three hand-added indexes (they weren't
declared on the models at the time) and created the speaker FK unnamed.
This revision converges both fresh and already-migrated databases on the
model-declared state; every statement is a no-op where already true.

Revision ID: e1a2b3c4d5f6
Revises: d6f3baa7b188
Create Date: 2026-07-11 17:30:00.000000

"""
from alembic import op

revision = 'e1a2b3c4d5f6'
down_revision = 'd6f3baa7b188'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_meetings_date")
    op.execute("DROP INDEX IF EXISTS idx_entity_mentions_entity")
    op.execute("DROP INDEX IF EXISTS idx_entity_updates_entity")
    op.execute("CREATE INDEX IF NOT EXISTS ix_meetings_meeting_date ON meetings (meeting_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entity_mentions_entity_id ON entity_mentions (entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entity_updates_entity_id ON entity_updates (entity_id)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'transcript_chunks_speaker_entity_id_fkey') THEN
                ALTER TABLE transcript_chunks
                    RENAME CONSTRAINT transcript_chunks_speaker_entity_id_fkey
                    TO fk_transcript_chunks_speaker_entity_id;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    pass  # repair-only; nothing meaningful to reverse
