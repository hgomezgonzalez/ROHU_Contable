"""Accounting corrections: AccountingError table, opening_confirmed on tenants,
cost_average_after on stock_movements, tenant_id on journal_lines,
timezone indexes for DIAN reports.

Revision ID: 0006_acct_fix
Revises: 0005_draft
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0006_acct_fix'
down_revision = '0005_draft'
branch_labels = None
depends_on = None


def upgrade():
    # 1. AccountingError table for tracking failed accounting entries
    op.create_table(
        'accounting_errors',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('sale_id', UUID(as_uuid=True),
                  sa.ForeignKey('sales.id'), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=False),
        sa.Column('status', sa.String(20), nullable=False,
                  server_default='pending'),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'failed')",
            name='ck_ae_status'),
    )
    op.create_index('idx_ae_tenant_status', 'accounting_errors',
                    ['tenant_id', 'status'])

    # 2. Opening confirmed flag on tenants
    op.add_column('tenants', sa.Column(
        'opening_confirmed', sa.Boolean, nullable=False,
        server_default=sa.text('false')))
    op.add_column('tenants', sa.Column(
        'opening_confirmed_at', sa.DateTime(timezone=True)))
    op.add_column('tenants', sa.Column(
        'opening_confirmed_by', UUID(as_uuid=True),
        sa.ForeignKey('users.id')))

    # 3. cost_average_after on stock_movements for kardex audit
    op.add_column('stock_movements', sa.Column(
        'cost_average_after', sa.Numeric(18, 6), nullable=False,
        server_default=sa.text('0')))

    # 4. tenant_id on journal_lines for direct queries and RLS
    op.add_column('journal_lines', sa.Column(
        'tenant_id', UUID(as_uuid=True), nullable=True))

    # Backfill tenant_id from journal_entries
    op.execute("""
        UPDATE journal_lines jl
        SET tenant_id = je.tenant_id
        FROM journal_entries je
        WHERE jl.entry_id = je.id
        AND jl.tenant_id IS NULL
    """)

    # Make NOT NULL after backfill
    op.alter_column('journal_lines', 'tenant_id', nullable=False)
    op.create_foreign_key(
        'fk_jl_tenant', 'journal_lines', 'tenants',
        ['tenant_id'], ['id'])
    op.create_index('idx_jl_tenant_account', 'journal_lines',
                    ['tenant_id', 'account_id'])

    # 5. Functional index for Bogota timezone on sales
    op.execute("""
        CREATE INDEX idx_sales_tenant_date_bogota
        ON sales (tenant_id, (sale_date AT TIME ZONE 'America/Bogota'))
    """)

    # 6. Index for OPENING uniqueness check per tenant
    op.create_index('idx_je_tenant_period_type', 'journal_entries',
                    ['tenant_id', 'period_id', 'entry_type'])

    # 7. Product cost history table
    op.create_table(
        'product_cost_history',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True),
                  sa.ForeignKey('products.id'), nullable=False),
        sa.Column('cost_before', sa.Numeric(18, 6), nullable=False),
        sa.Column('cost_after', sa.Numeric(18, 6), nullable=False),
        sa.Column('quantity_movement', sa.Numeric(12, 4), nullable=False),
        sa.Column('reference_type', sa.String(50)),
        sa.Column('reference_id', UUID(as_uuid=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
    )
    op.create_index('idx_pch_tenant_product_date', 'product_cost_history',
                    ['tenant_id', 'product_id', sa.text('created_at DESC')])

    # 8. Accounting reconciliations table
    op.create_table(
        'accounting_reconciliations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('period_id', UUID(as_uuid=True),
                  sa.ForeignKey('accounting_periods.id')),
        sa.Column('reconciliation_date', sa.DateTime(timezone=True),
                  nullable=False),
        sa.Column('inventory_book_value', sa.Numeric(18, 2), nullable=False),
        sa.Column('inventory_physical_value', sa.Numeric(18, 2),
                  nullable=False),
        sa.Column('difference', sa.Numeric(18, 2), nullable=False),
        sa.Column('status', sa.String(20), nullable=False,
                  server_default='pending'),
        sa.Column('adjustment_entry_id', UUID(as_uuid=True),
                  sa.ForeignKey('journal_entries.id')),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reconciled_at', sa.DateTime(timezone=True)),
        sa.Column('reconciled_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id')),
        sa.CheckConstraint(
            "status IN ('pending', 'reconciled', 'adjusted')",
            name='ck_ar_status'),
    )
    op.create_index('idx_ar_tenant_period', 'accounting_reconciliations',
                    ['tenant_id', 'period_id'])

    # 9. Inventory period snapshots table
    op.create_table(
        'inventory_period_snapshots',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('period_id', UUID(as_uuid=True),
                  sa.ForeignKey('accounting_periods.id'), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True),
                  sa.ForeignKey('products.id'), nullable=False),
        sa.Column('opening_stock', sa.Numeric(12, 4), nullable=False),
        sa.Column('opening_value', sa.Numeric(18, 2), nullable=False),
        sa.Column('entries_qty', sa.Numeric(12, 4), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('exits_qty', sa.Numeric(12, 4), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('closing_stock', sa.Numeric(12, 4), nullable=False),
        sa.Column('closing_cost_average', sa.Numeric(18, 6), nullable=False),
        sa.Column('closing_value', sa.Numeric(18, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.UniqueConstraint('tenant_id', 'period_id', 'product_id',
                            name='uq_ips_tenant_period_product'),
        sa.CheckConstraint('closing_stock >= 0', name='ck_ips_stock'),
        sa.CheckConstraint('closing_value >= 0', name='ck_ips_value'),
    )


def downgrade():
    op.drop_table('inventory_period_snapshots')
    op.drop_table('accounting_reconciliations')
    op.drop_index('idx_pch_tenant_product_date')
    op.drop_table('product_cost_history')
    op.drop_index('idx_je_tenant_period_type', 'journal_entries')
    op.execute('DROP INDEX IF EXISTS idx_sales_tenant_date_bogota')
    op.drop_index('idx_jl_tenant_account', 'journal_lines')
    op.drop_constraint('fk_jl_tenant', 'journal_lines', type_='foreignkey')
    op.drop_column('journal_lines', 'tenant_id')
    op.drop_column('stock_movements', 'cost_average_after')
    op.drop_column('tenants', 'opening_confirmed_by')
    op.drop_column('tenants', 'opening_confirmed_at')
    op.drop_column('tenants', 'opening_confirmed')
    op.drop_index('idx_ae_tenant_status')
    op.drop_table('accounting_errors')
