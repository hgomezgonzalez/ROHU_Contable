"""Add index on withholding_configs for performance

Revision ID: 0004_wc_idx
Revises: 0003_opening
Create Date: 2026-03-30
"""
from alembic import op

revision = '0004_wc_idx'
down_revision = '0003_opening'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_wc_tenant_active', 'withholding_configs',
        ['tenant_id', 'is_active'],
        postgresql_where='is_active = true'
    )


def downgrade():
    op.drop_index('ix_wc_tenant_active', 'withholding_configs')
