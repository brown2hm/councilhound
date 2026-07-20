"""topic_subscriptions: follow-a-topic email subscriptions

Revision ID: a7c2e9d41b03
Revises: 9b4d1e6c2a80
Create Date: 2026-07-20 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'a7c2e9d41b03'
down_revision = '9b4d1e6c2a80'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'topic_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('confirmed', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('last_update_id', sa.Integer(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', 'entity_id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index(op.f('ix_topic_subscriptions_entity_id'),
                    'topic_subscriptions', ['entity_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_topic_subscriptions_entity_id'),
                  table_name='topic_subscriptions')
    op.drop_table('topic_subscriptions')
