"""Voucher models — VoucherType, Voucher, VoucherTransaction."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class VoucherType(db.Model):
    """Template for a type of discount voucher."""

    __tablename__ = "voucher_types"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    face_value = db.Column(db.Numeric(18, 2), nullable=False)
    validity_days = db.Column(db.Integer, nullable=False)
    max_issuable = db.Column(db.Integer, nullable=True)
    issued_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="active")
    color_hex = db.Column(db.String(7), nullable=True)
    design_template = db.Column(db.String(50), nullable=True, default="default")
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    updated_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)

    vouchers = db.relationship("Voucher", back_populates="voucher_type", lazy="dynamic")

    __table_args__ = (
        Index("idx_vt_tenant_status", "tenant_id", "status"),
        CheckConstraint("face_value > 0", name="ck_vt_face_value"),
        CheckConstraint("validity_days >= 90", name="ck_vt_validity_min"),
        CheckConstraint("issued_count >= 0", name="ck_vt_issued_count"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_vt_status"),
    )

    def __repr__(self):
        return f"<VoucherType {self.name} ${self.face_value}>"

    @property
    def is_active(self):
        return self.status == "active" and self.deleted_at is None

    @property
    def can_issue(self):
        if not self.is_active:
            return False
        if self.max_issuable is not None and self.issued_count >= self.max_issuable:
            return False
        return True


class Voucher(db.Model):
    """Individual discount voucher instance."""

    __tablename__ = "vouchers"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    voucher_type_id = db.Column(UUID(as_uuid=True), db.ForeignKey("voucher_types.id"), nullable=False)

    code = db.Column(db.String(25), nullable=False, unique=True)
    status = db.Column(db.String(25), nullable=False, default="issued")

    face_value = db.Column(db.Numeric(18, 2), nullable=False)
    remaining_balance = db.Column(db.Numeric(18, 2), nullable=False)

    issued_at = db.Column(db.DateTime(timezone=True), nullable=True)
    sold_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    fully_redeemed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    purchase_sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)
    buyer_customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=True)
    buyer_name = db.Column(db.String(255), nullable=True)
    buyer_id_document = db.Column(db.String(30), nullable=True)

    print_count = db.Column(db.Integer, nullable=False, default=0)
    last_printed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    idempotency_key = db.Column(db.String(100), nullable=True, unique=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    updated_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)

    voucher_type = db.relationship("VoucherType", back_populates="vouchers")
    transactions = db.relationship(
        "VoucherTransaction", back_populates="voucher", lazy="dynamic", order_by="VoucherTransaction.occurred_at.desc()"
    )

    __table_args__ = (
        Index("idx_v_tenant_status", "tenant_id", "status"),
        Index("idx_v_tenant_type", "tenant_id", "voucher_type_id"),
        Index("idx_v_tenant_expires", "tenant_id", "expires_at"),
        Index("idx_v_purchase_sale", "purchase_sale_id"),
        CheckConstraint("face_value > 0", name="ck_v_face_value"),
        CheckConstraint("remaining_balance >= 0", name="ck_v_remaining_balance"),
        CheckConstraint("remaining_balance <= face_value", name="ck_v_balance_le_face"),
        CheckConstraint("print_count >= 0", name="ck_v_print_count"),
        CheckConstraint(
            "status IN ('issued', 'sold', 'partially_redeemed', " "'redeemed', 'expired', 'cancelled')",
            name="ck_v_status",
        ),
    )

    def __repr__(self):
        return f"<Voucher {self.code} ${self.face_value} [{self.status}]>"

    @property
    def is_redeemable(self):
        return self.status in ("sold", "partially_redeemed")

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at


class VoucherTransaction(db.Model):
    """Immutable audit log of voucher movements."""

    __tablename__ = "voucher_transactions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    voucher_id = db.Column(UUID(as_uuid=True), db.ForeignKey("vouchers.id"), nullable=False)

    transaction_type = db.Column(db.String(30), nullable=False)
    amount_change = db.Column(db.Numeric(18, 2), nullable=False)
    balance_before = db.Column(db.Numeric(18, 2), nullable=False)
    balance_after = db.Column(db.Numeric(18, 2), nullable=False)

    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)
    payment_id = db.Column(UUID(as_uuid=True), db.ForeignKey("payments.id"), nullable=True)
    journal_entry_id = db.Column(UUID(as_uuid=True), db.ForeignKey("journal_entries.id"), nullable=True)

    performed_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    idempotency_key = db.Column(db.String(100), nullable=False, unique=True)
    ip_address = db.Column(db.String(45), nullable=True)

    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    voucher = db.relationship("Voucher", back_populates="transactions")

    __table_args__ = (
        Index("idx_vtx_voucher_occurred", "voucher_id", occurred_at.desc()),
        Index("idx_vtx_tenant_type_date", "tenant_id", "transaction_type", occurred_at.desc()),
        Index("idx_vtx_sale", "sale_id"),
        CheckConstraint("balance_before >= 0", name="ck_vtx_balance_before"),
        CheckConstraint("balance_after >= 0", name="ck_vtx_balance_after"),
        CheckConstraint(
            "transaction_type IN ('issued', 'sold', 'redeemed', "
            "'expired', 'cancelled', 'adjusted', 'refund_new_voucher')",
            name="ck_vtx_type",
        ),
    )

    def __repr__(self):
        return f"<VoucherTx {self.transaction_type} {self.amount_change}>"
