"""Add performance indexes for FK columns and frequent queries

Revision ID: 0002_perf_idx
Revises: 0001_initial
Create Date: 2026-03-30
"""
from alembic import op

revision = '0002_perf_idx'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    # ── FK indexes (PostgreSQL does NOT auto-index FKs) ──
    op.create_index('ix_si_sale_id', 'sale_items', ['sale_id'])
    op.create_index('ix_pay_sale_id', 'payments', ['sale_id'])
    op.create_index('ix_jl_entry_id', 'journal_lines', ['entry_id'])
    op.create_index('ix_poi_order_id', 'purchase_order_items', ['order_id'])
    op.create_index('ix_roles_tenant_id', 'roles', ['tenant_id'])
    op.create_index('ix_cn_sale_id', 'credit_notes', ['sale_id'])
    op.create_index('ix_cni_cn_id', 'credit_note_items', ['credit_note_id'])

    # ── Composite indexes for frequent queries ──
    op.create_index('ix_sales_tenant_customer', 'sales', ['tenant_id', 'customer_id'],
                    postgresql_where="customer_id IS NOT NULL")
    op.create_index('ix_sales_tenant_pay_status', 'sales', ['tenant_id', 'payment_status'])
    op.create_index('ix_sales_tenant_session', 'sales', ['tenant_id', 'cash_session_id'])
    op.create_index('ix_si_product_id', 'sale_items', ['product_id'])
    op.create_index('ix_je_tenant_period', 'journal_entries', ['tenant_id', 'period_id'])
    op.create_index('ix_je_tenant_type', 'journal_entries', ['tenant_id', 'entry_type'])

    # ── Drop redundant index ──
    op.drop_index('ix_audit_logs_tenant_id', 'audit_logs')


def downgrade():
    op.create_index('ix_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])

    op.drop_index('ix_je_tenant_type', 'journal_entries')
    op.drop_index('ix_je_tenant_period', 'journal_entries')
    op.drop_index('ix_si_product_id', 'sale_items')
    op.drop_index('ix_sales_tenant_session', 'sales')
    op.drop_index('ix_sales_tenant_pay_status', 'sales')
    op.drop_index('ix_sales_tenant_customer', 'sales')
    op.drop_index('ix_cni_cn_id', 'credit_note_items')
    op.drop_index('ix_cn_sale_id', 'credit_notes')
    op.drop_index('ix_roles_tenant_id', 'roles')
    op.drop_index('ix_poi_order_id', 'purchase_order_items')
    op.drop_index('ix_jl_entry_id', 'journal_lines')
    op.drop_index('ix_pay_sale_id', 'payments')
    op.drop_index('ix_si_sale_id', 'sale_items')
