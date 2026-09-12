"""topic_subscriptions: follow a member, a body, an area, or the weekly briefing

Revision ID: b3c4d5e6f7a8
Revises: a7c2e9d41b03
Create Date: 2026-09-12 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'b3c4d5e6f7a8'
down_revision = 'a7c2e9d41b03'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('topic_subscriptions_email_entity_id_key',
                       'topic_subscriptions', type_='unique')
    op.alter_column('topic_subscriptions', 'entity_id', nullable=True)
    op.add_column('topic_subscriptions',
                  sa.Column('kind', sa.String(), nullable=False, server_default='topic'))
    op.add_column('topic_subscriptions', sa.Column('body', sa.String(), nullable=True))
    op.add_column('topic_subscriptions', sa.Column('lat', sa.Numeric(), nullable=True))
    op.add_column('topic_subscriptions', sa.Column('lng', sa.Numeric(), nullable=True))
    op.add_column('topic_subscriptions', sa.Column('radius_m', sa.Integer(), nullable=True))
    op.add_column('topic_subscriptions', sa.Column('label', sa.Text(), nullable=True))
    op.add_column('topic_subscriptions',
                  sa.Column('last_vote_id', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('topic_subscriptions',
                  sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # rows the old schema can't represent go with the columns
    op.execute("DELETE FROM topic_subscriptions WHERE kind <> 'topic' OR entity_id IS NULL")
    for col in ('last_sent_at', 'last_vote_id', 'label', 'radius_m', 'lng', 'lat',
                'body', 'kind'):
        op.drop_column('topic_subscriptions', col)
    op.alter_column('topic_subscriptions', 'entity_id', nullable=False)
    op.create_unique_constraint('topic_subscriptions_email_entity_id_key',
                                'topic_subscriptions', ['email', 'entity_id'])
