"""Add voucher module: voucher_types, vouchers, voucher_transactions tables,
ALTER payments.method CHECK, ADD voucher_id to journal_entries,
ADD new entry_types to journal_entries CHECK.

Revision ID: 0007_vouchers
Revises: 0006_acct_fix
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0007_vouchers'
down_revision = '0006_acct_fix'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. voucher_types ──────────────────────────────────────────────
    op.create_table(
        'voucher_types',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('face_value', sa.Numeric(18, 2), nullable=False),
        sa.Column('validity_days', sa.Integer, nullable=False),
        sa.Column('max_issuable', sa.Integer, nullable=True),
        sa.Column('issued_count', sa.Integer, nullable=False,
                  server_default=sa.text('0')),
        sa.Column('status', sa.String(20), nullable=False,
                  server_default='active'),
        sa.Column('color_hex', sa.String(7), nullable=True),
        sa.Column('design_template', sa.String(50), nullable=True,
                  server_default='default'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('version', sa.Integer, nullable=False,
                  server_default=sa.text('1')),
        sa.CheckConstraint('face_value > 0', name='ck_vt_face_value'),
        sa.CheckConstraint('validity_days >= 90', name='ck_vt_validity_min'),
        sa.CheckConstraint('issued_count >= 0', name='ck_vt_issued_count'),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name='ck_vt_status'),
    )
    op.create_index('idx_vt_tenant_status', 'voucher_types',
                    ['tenant_id', 'status'])

    # ── 2. vouchers ───────────────────────────────────────────────────
    op.create_table(
        'vouchers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('voucher_type_id', UUID(as_uuid=True),
                  sa.ForeignKey('voucher_types.id'), nullable=False),
        sa.Column('code', sa.String(25), nullable=False, unique=True),
        sa.Column('status', sa.String(25), nullable=False,
                  server_default='issued'),
        sa.Column('face_value', sa.Numeric(18, 2), nullable=False),
        sa.Column('remaining_balance', sa.Numeric(18, 2), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sold_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fully_redeemed_at', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('purchase_sale_id', UUID(as_uuid=True),
                  sa.ForeignKey('sales.id'), nullable=True),
        sa.Column('buyer_customer_id', UUID(as_uuid=True),
                  sa.ForeignKey('customers.id'), nullable=True),
        sa.Column('buyer_name', sa.String(255), nullable=True),
        sa.Column('buyer_id_document', sa.String(30), nullable=True),
        sa.Column('print_count', sa.Integer, nullable=False,
                  server_default=sa.text('0')),
        sa.Column('last_printed_at', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('idempotency_key', sa.String(100), nullable=True,
                  unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('version', sa.Integer, nullable=False,
                  server_default=sa.text('1')),
        sa.CheckConstraint('face_value > 0', name='ck_v_face_value'),
        sa.CheckConstraint('remaining_balance >= 0',
                           name='ck_v_remaining_balance'),
        sa.CheckConstraint('remaining_balance <= face_value',
                           name='ck_v_balance_le_face'),
        sa.CheckConstraint('print_count >= 0', name='ck_v_print_count'),
        sa.CheckConstraint(
            "status IN ('issued', 'sold', 'partially_redeemed', "
            "'redeemed', 'expired', 'cancelled')",
            name='ck_v_status'),
    )
    op.create_index('idx_v_tenant_status', 'vouchers',
                    ['tenant_id', 'status'])
    op.create_index('idx_v_tenant_type', 'vouchers',
                    ['tenant_id', 'voucher_type_id'])
    op.create_index('idx_v_tenant_expires', 'vouchers',
                    ['tenant_id', 'expires_at'])
    op.create_index('idx_v_purchase_sale', 'vouchers',
                    ['purchase_sale_id'])

    # Trigger to prevent face_value modification after creation
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_voucher_value_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.face_value != NEW.face_value THEN
                RAISE EXCEPTION 'face_value is immutable after voucher creation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER voucher_immutable_value
            BEFORE UPDATE ON vouchers
            FOR EACH ROW EXECUTE FUNCTION prevent_voucher_value_modification();
    """)

    # ── 3. voucher_transactions ───────────────────────────────────────
    op.create_table(
        'voucher_transactions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('voucher_id', UUID(as_uuid=True),
                  sa.ForeignKey('vouchers.id'), nullable=False),
        sa.Column('transaction_type', sa.String(30), nullable=False),
        sa.Column('amount_change', sa.Numeric(18, 2), nullable=False),
        sa.Column('balance_before', sa.Numeric(18, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(18, 2), nullable=False),
        sa.Column('sale_id', UUID(as_uuid=True),
                  sa.ForeignKey('sales.id'), nullable=True),
        sa.Column('payment_id', UUID(as_uuid=True),
                  sa.ForeignKey('payments.id'), nullable=True),
        sa.Column('journal_entry_id', UUID(as_uuid=True),
                  sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('performed_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('idempotency_key', sa.String(100), nullable=False,
                  unique=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.CheckConstraint('balance_before >= 0',
                           name='ck_vtx_balance_before'),
        sa.CheckConstraint('balance_after >= 0',
                           name='ck_vtx_balance_after'),
        sa.CheckConstraint(
            "transaction_type IN ('issued', 'sold', 'redeemed', "
            "'expired', 'cancelled', 'adjusted', 'refund_new_voucher')",
            name='ck_vtx_type'),
    )
    op.create_index('idx_vtx_voucher_occurred', 'voucher_transactions',
                    ['voucher_id', sa.text('occurred_at DESC')])
    op.create_index('idx_vtx_tenant_type_date', 'voucher_transactions',
                    ['tenant_id', 'transaction_type',
                     sa.text('occurred_at DESC')])
    op.create_index('idx_vtx_sale', 'voucher_transactions', ['sale_id'])

    # ── 4. ALTER payments.method CHECK to include 'voucher' ───────────
    # Drop existing constraint (may be named ck_pay_method or ck_payments_method)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE payments DROP CONSTRAINT IF EXISTS ck_pay_method;
            ALTER TABLE payments DROP CONSTRAINT IF EXISTS ck_payments_method;
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$;
    """)
    op.create_check_constraint(
        'ck_pay_method', 'payments',
        "method IN ('cash', 'card', 'transfer', 'nequi', "
        "'daviplata', 'mixed', 'voucher')")

    # ── 5. ADD voucher_id to journal_entries ──────────────────────────
    op.add_column('journal_entries', sa.Column(
        'voucher_id', UUID(as_uuid=True),
        sa.ForeignKey('vouchers.id'), nullable=True))
    op.create_index('idx_je_voucher', 'journal_entries',
                    ['voucher_id'])

    # ── 6. ADD new entry_types to journal_entries CHECK ───────────────
    op.execute("ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS ck_je_type")
    op.create_check_constraint(
        'ck_je_type', 'journal_entries',
        "entry_type IN ('SALE', 'SALE_COST', 'PURCHASE', 'PAYMENT', "
        "'ADJUSTMENT', 'REVERSAL', 'MANUAL', 'CLOSING', "
        "'CASH_RECEIPT', 'CASH_DISBURSEMENT', 'TRANSFER', "
        "'EXPENSE', 'SUPPLIER_PAYMENT', 'CREDIT_NOTE_PURCHASE', "
        "'DEBIT_NOTE', 'SALES_DEBIT_NOTE', 'OPENING', "
        "'VOUCHER_SALE', 'VOUCHER_REDEMPTION', 'VOUCHER_EXPIRY')")


def downgrade():
    # Restore original journal_entries CHECK
    op.execute("ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS ck_je_type")
    op.create_check_constraint(
        'ck_je_type', 'journal_entries',
        "entry_type IN ('SALE', 'SALE_COST', 'PURCHASE', 'PAYMENT', "
        "'ADJUSTMENT', 'REVERSAL', 'MANUAL', 'CLOSING', "
        "'CASH_RECEIPT', 'CASH_DISBURSEMENT', 'TRANSFER', "
        "'EXPENSE', 'SUPPLIER_PAYMENT', 'CREDIT_NOTE_PURCHASE', "
        "'DEBIT_NOTE', 'SALES_DEBIT_NOTE', 'OPENING')")

    # Remove voucher_id from journal_entries
    op.drop_index('idx_je_voucher', 'journal_entries')
    op.drop_column('journal_entries', 'voucher_id')

    # Restore original payments CHECK
    try:
        op.drop_constraint('ck_pay_method', 'payments', type_='check')
    except Exception:
        pass
    op.create_check_constraint(
        'ck_pay_method', 'payments',
        "method IN ('cash', 'card', 'transfer', 'nequi', "
        "'daviplata', 'mixed')")

    # Drop voucher tables (reverse order)
    op.drop_table('voucher_transactions')
    op.execute('DROP TRIGGER IF EXISTS voucher_immutable_value ON vouchers')
    op.execute('DROP FUNCTION IF EXISTS prevent_voucher_value_modification()')
    op.drop_table('vouchers')
    op.drop_table('voucher_types')
