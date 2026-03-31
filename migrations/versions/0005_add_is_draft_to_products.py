"""Add is_draft field to products for OC with new products

Revision ID: 0005_draft
Revises: 0004_wc_idx
Create Date: 2026-03-31
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_draft'
down_revision = '0004_wc_idx'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('products', sa.Column('is_draft', sa.Boolean(), server_default='false', nullable=False))


def downgrade():
    op.drop_column('products', 'is_draft')
