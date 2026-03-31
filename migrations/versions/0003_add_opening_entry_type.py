"""Add OPENING to journal entry type constraint

Revision ID: 0003_opening
Revises: 0002_perf_idx
Create Date: 2026-03-30
"""
from alembic import op

revision = '0003_opening'
down_revision = '0002_perf_idx'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_je_type', 'journal_entries', type_='check')
    op.create_check_constraint(
        'ck_je_type', 'journal_entries',
        "entry_type IN ('SALE','SALE_COST','PURCHASE','PAYMENT','ADJUSTMENT','REVERSAL',"
        "'MANUAL','CLOSING','CASH_RECEIPT','CASH_DISBURSEMENT','TRANSFER','EXPENSE',"
        "'SUPPLIER_PAYMENT','CREDIT_NOTE_PURCHASE','DEBIT_NOTE','SALES_DEBIT_NOTE','OPENING')"
    )


def downgrade():
    op.drop_constraint('ck_je_type', 'journal_entries', type_='check')
    op.create_check_constraint(
        'ck_je_type', 'journal_entries',
        "entry_type IN ('SALE','SALE_COST','PURCHASE','PAYMENT','ADJUSTMENT','REVERSAL',"
        "'MANUAL','CLOSING','CASH_RECEIPT','CASH_DISBURSEMENT','TRANSFER','EXPENSE',"
        "'SUPPLIER_PAYMENT','CREDIT_NOTE_PURCHASE','DEBIT_NOTE','SALES_DEBIT_NOTE')"
    )
