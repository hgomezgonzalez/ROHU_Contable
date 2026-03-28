"""Cash models — Receipts, Disbursements, Transfers, Cash Count Details."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class CashReceipt(db.Model):
    """Cash receipt — money coming IN (customer payments, other income, etc.)."""

    __tablename__ = "cash_receipts"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    cash_session_id = db.Column(UUID(as_uuid=True), db.ForeignKey("cash_sessions.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    receipt_number = db.Column(db.String(30), nullable=False)
    receipt_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    source_type = db.Column(db.String(30), nullable=False)
    source_id = db.Column(UUID(as_uuid=True), nullable=True)
    source_name = db.Column(db.String(255))
    concept = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    payment_method = db.Column(db.String(30), nullable=False, default="cash")
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="active")
    voided_at = db.Column(db.DateTime(timezone=True))
    voided_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "receipt_number", name="uq_cr_tenant_number"),
        Index("idx_cr_tenant_date", "tenant_id", "receipt_date"),
        CheckConstraint("amount > 0", name="ck_cr_amount"),
        CheckConstraint(
            "source_type IN ('customer_payment', 'other_income', 'loan', 'partner_capital')",
            name="ck_cr_source_type"
        ),
        CheckConstraint(
            "payment_method IN ('cash', 'transfer', 'check', 'nequi', 'daviplata')",
            name="ck_cr_method"
        ),
        CheckConstraint("status IN ('active', 'voided')", name="ck_cr_status"),
    )

    def __repr__(self):
        return f"<CashReceipt {self.receipt_number} ${self.amount}>"


class CashDisbursement(db.Model):
    """Cash disbursement — money going OUT (supplier payments, expenses, etc.)."""

    __tablename__ = "cash_disbursements"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    cash_session_id = db.Column(UUID(as_uuid=True), db.ForeignKey("cash_sessions.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    disbursement_number = db.Column(db.String(30), nullable=False)
    disbursement_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    destination_type = db.Column(db.String(30), nullable=False)
    destination_id = db.Column(UUID(as_uuid=True), nullable=True)
    destination_name = db.Column(db.String(255))
    concept = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    payment_method = db.Column(db.String(30), nullable=False, default="cash")
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)

    puc_code = db.Column(db.String(10), nullable=True)

    approved_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True))

    status = db.Column(db.String(20), nullable=False, default="active")
    voided_at = db.Column(db.DateTime(timezone=True))
    voided_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "disbursement_number", name="uq_cd_tenant_number"),
        Index("idx_cd_tenant_date", "tenant_id", "disbursement_date"),
        CheckConstraint("amount > 0", name="ck_cd_amount"),
        CheckConstraint(
            "destination_type IN ('supplier_payment', 'expense', 'petty_cash', 'bank_transfer', 'other')",
            name="ck_cd_dest_type"
        ),
        CheckConstraint(
            "payment_method IN ('cash', 'transfer', 'check', 'nequi', 'daviplata')",
            name="ck_cd_method"
        ),
        CheckConstraint("status IN ('active', 'voided')", name="ck_cd_status"),
    )

    def __repr__(self):
        return f"<CashDisbursement {self.disbursement_number} ${self.amount}>"


class CashTransfer(db.Model):
    """Transfer between cash/bank accounts (caja -> banco, banco -> caja, etc.)."""

    __tablename__ = "cash_transfers"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    transfer_number = db.Column(db.String(30), nullable=False)
    transfer_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    from_account_puc = db.Column(db.String(10), nullable=False)
    to_account_puc = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="completed")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "transfer_number", name="uq_ct_tenant_number"),
        CheckConstraint("amount > 0", name="ck_ct_amount"),
        CheckConstraint("from_account_puc != to_account_puc", name="ck_ct_diff_accounts"),
        CheckConstraint("status IN ('completed', 'voided')", name="ck_ct_status"),
    )

    def __repr__(self):
        return f"<CashTransfer {self.transfer_number} {self.from_account_puc}->{self.to_account_puc}>"


class CashCountDetail(db.Model):
    """Denomination detail for a cash session close (arqueo)."""

    __tablename__ = "cash_count_details"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    cash_session_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("cash_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    denomination = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("denomination > 0", name="ck_ccd_denomination"),
        CheckConstraint("quantity >= 0", name="ck_ccd_quantity"),
    )

    def __repr__(self):
        return f"<CashCount ${self.denomination} x{self.quantity}>"
