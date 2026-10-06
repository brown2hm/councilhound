"""project_document_chunks: searchable passages of development-project documents

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-06 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = 'e8f9a0b1c2d3'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'project_document_chunks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('city_project_id', sa.Integer(),
                  sa.ForeignKey('city_projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('doc_url', sa.Text(), nullable=False),
        sa.Column('doc_label', sa.Text(), nullable=False),
        sa.Column('doc_date', sa.Date()),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(768)),
        sa.Column('indexed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('doc_url', 'ordinal'),
    )
    op.create_index('ix_project_document_chunks_city_project_id', 'project_document_chunks',
                    ['city_project_id'])


def downgrade() -> None:
    op.drop_index('ix_project_document_chunks_city_project_id', table_name='project_document_chunks')
    op.drop_table('project_document_chunks')
