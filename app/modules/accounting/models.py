"""Accounting models — Chart of Accounts (PUC), Journal Entries, Periods."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class AccountingPeriod(db.Model):
    """Fiscal period (monthly). Controls when entries can be posted."""

    __tablename__ = "accounting_periods"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")
    closed_at = db.Column(db.DateTime(timezone=True))
    closed_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    entries = db.relationship("JournalEntry", back_populates="period", lazy="dynamic")

    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "month", name="uq_periods_tenant_year_month"),
        CheckConstraint("status IN ('open', 'closed', 'locked')", name="ck_periods_status"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_periods_month"),
    )

    def __repr__(self):
        return f"<Period {self.year}-{self.month:02d} ({self.status})>"


class ChartOfAccount(db.Model):
    """PUC account for a tenant. System accounts are seeded; custom are addable."""

    __tablename__ = "chart_of_accounts"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    puc_code = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    account_type = db.Column(db.String(20), nullable=False)
    normal_balance = db.Column(db.String(10), nullable=False)
    parent_code = db.Column(db.String(10))
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    version = db.Column(db.Integer, nullable=False, default=1)

    lines = db.relationship("JournalLine", back_populates="account", lazy="dynamic")

    __table_args__ = (
        UniqueConstraint("tenant_id", "puc_code", name="uq_coa_tenant_puc"),
        Index("idx_coa_tenant_type", "tenant_id", "account_type"),
        CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'income', 'expense', 'cost')",
            name="ck_coa_type"
        ),
        CheckConstraint("normal_balance IN ('debit', 'credit')", name="ck_coa_balance"),
    )

    def __repr__(self):
        return f"<Account {self.puc_code} {self.name}>"


class JournalEntry(db.Model):
    """Immutable accounting entry. Double-entry: sum(debits) = sum(credits)."""

    __tablename__ = "journal_entries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    period_id = db.Column(UUID(as_uuid=True), db.ForeignKey("accounting_periods.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    entry_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    entry_type = db.Column(db.String(30), nullable=False)
    description = db.Column(db.String(500), nullable=False)

    source_document_type = db.Column(db.String(50))
    source_document_id = db.Column(UUID(as_uuid=True))

    is_reversed = db.Column(db.Boolean, nullable=False, default=False)
    reversal_of_id = db.Column(UUID(as_uuid=True), db.ForeignKey("journal_entries.id"))

    total_debit = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_credit = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    lines = db.relationship("JournalLine", back_populates="entry", lazy="joined", cascade="all, delete-orphan")
    period = db.relationship("AccountingPeriod", back_populates="entries")

    __table_args__ = (
        Index("idx_je_tenant_date", "tenant_id", "entry_date"),
        Index("idx_je_source", "source_document_type", "source_document_id"),
        CheckConstraint(
            "entry_type IN ('SALE', 'SALE_COST', 'PURCHASE', 'PAYMENT', "
            "'ADJUSTMENT', 'REVERSAL', 'MANUAL', 'CLOSING', "
            "'CASH_RECEIPT', 'CASH_DISBURSEMENT', 'TRANSFER', "
            "'EXPENSE', 'SUPPLIER_PAYMENT', 'CREDIT_NOTE_PURCHASE', 'DEBIT_NOTE', 'SALES_DEBIT_NOTE')",
            name="ck_je_type"
        ),
    )

    def __repr__(self):
        return f"<JournalEntry {self.entry_type} ${self.total_debit}>"


class JournalLine(db.Model):
    """Single debit or credit line within a journal entry."""

    __tablename__ = "journal_lines"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entry_id = db.Column(UUID(as_uuid=True), db.ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False)
    account_id = db.Column(UUID(as_uuid=True), db.ForeignKey("chart_of_accounts.id"), nullable=False)

    debit_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    credit_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    description = db.Column(db.String(255))

    entry = db.relationship("JournalEntry", back_populates="lines")
    account = db.relationship("ChartOfAccount", back_populates="lines")

    __table_args__ = (
        Index("idx_jl_account", "account_id"),
        CheckConstraint("debit_amount >= 0", name="ck_jl_debit"),
        CheckConstraint("credit_amount >= 0", name="ck_jl_credit"),
        CheckConstraint(
            "(debit_amount > 0 AND credit_amount = 0) OR (debit_amount = 0 AND credit_amount > 0)",
            name="ck_jl_exclusive"
        ),
    )

    def __repr__(self):
        if self.debit_amount > 0:
            return f"<Line D ${self.debit_amount}>"
        return f"<Line C ${self.credit_amount}>"


class Expense(db.Model):
    """Expense record — operational expenses with causation/payment support."""

    __tablename__ = "expenses"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    expense_number = db.Column(db.String(30), nullable=False)
    expense_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    puc_code = db.Column(db.String(10), nullable=False)
    concept = db.Column(db.String(255), nullable=False)

    amount = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False)

    supplier_id = db.Column(UUID(as_uuid=True), db.ForeignKey("suppliers.id"), nullable=True)
    payment_status = db.Column(db.String(20), nullable=False, default="paid")
    payment_method = db.Column(db.String(30))
    receipt_reference = db.Column(db.String(100))
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="active")
    paid_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "expense_number", name="uq_exp_tenant_number"),
        Index("idx_exp_tenant_date", "tenant_id", "expense_date"),
        CheckConstraint("amount > 0", name="ck_exp_amount"),
        CheckConstraint(
            "payment_status IN ('paid', 'pending')",
            name="ck_exp_pay_status"
        ),
        CheckConstraint("status IN ('active', 'voided')", name="ck_exp_status"),
    )

    def __repr__(self):
        return f"<Expense {self.expense_number} ${self.total_amount}>"


class WithholdingConfig(db.Model):
    """Withholding tax configuration (retefuente, reteICA, reteIVA)."""

    __tablename__ = "withholding_configs"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)

    type = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    rate = db.Column(db.Numeric(8, 4), nullable=False)
    base_uvt = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    puc_code = db.Column(db.String(10), nullable=False)
    applies_to = db.Column(db.String(20), nullable=False, default="purchases")

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "type IN ('retefuente', 'reteica', 'reteiva')",
            name="ck_wc_type"
        ),
        CheckConstraint(
            "applies_to IN ('purchases', 'sales', 'both')",
            name="ck_wc_applies"
        ),
        CheckConstraint("rate > 0 AND rate <= 100", name="ck_wc_rate"),
    )

    def __repr__(self):
        return f"<WithholdingConfig {self.type} {self.rate}%>"
