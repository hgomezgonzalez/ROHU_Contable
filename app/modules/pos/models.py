"""POS models — Sales, SaleItems, Payments, CashSessions."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class CashSession(db.Model):
    """Represents an open/closed cash register session."""

    __tablename__ = "cash_sessions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    opened_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    closed_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))

    opening_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    closing_amount = db.Column(db.Numeric(18, 2))
    expected_amount = db.Column(db.Numeric(18, 2))
    difference = db.Column(db.Numeric(18, 2))

    status = db.Column(db.String(20), nullable=False, default="open")
    opened_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    closed_at = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.Text)

    sales = db.relationship("Sale", back_populates="cash_session", lazy="dynamic")

    __table_args__ = (
        Index("idx_cash_sessions_tenant_status", "tenant_id", "status"),
        CheckConstraint("status IN ('open', 'closed')", name="ck_cash_sessions_status"),
        CheckConstraint("opening_amount >= 0", name="ck_cash_sessions_opening"),
    )

    def __repr__(self):
        return f"<CashSession {self.status} opened_at={self.opened_at}>"


class Sale(db.Model):
    """A completed or voided sale transaction."""

    __tablename__ = "sales"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    cash_session_id = db.Column(UUID(as_uuid=True), db.ForeignKey("cash_sessions.id"), nullable=True)
    cashier_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    invoice_number = db.Column(db.String(30), nullable=False)
    sale_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    status = db.Column(db.String(20), nullable=False, default="completed")

    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    discount_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=True)
    customer_name = db.Column(db.String(255))
    customer_tax_id = db.Column(db.String(20))

    sale_type = db.Column(db.String(20), nullable=False, default="cash")
    credit_days = db.Column(db.Integer, nullable=False, default=0)
    due_date = db.Column(db.DateTime(timezone=True))
    payment_status = db.Column(db.String(20), nullable=False, default="paid")
    amount_paid = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    amount_due = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    notes = db.Column(db.Text)

    voided_at = db.Column(db.DateTime(timezone=True))
    voided_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))
    void_reason = db.Column(db.String(255))

    idempotency_key = db.Column(UUID(as_uuid=True), unique=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    version = db.Column(db.Integer, nullable=False, default=1)

    items = db.relationship("SaleItem", back_populates="sale", lazy="select", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="sale", lazy="select", cascade="all, delete-orphan")
    cash_session = db.relationship("CashSession", back_populates="sales")

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_sales_tenant_invoice"),
        Index("idx_sales_tenant_date", "tenant_id", "sale_date"),
        Index("idx_sales_tenant_status", "tenant_id", "status"),
        Index("idx_sales_cashier", "tenant_id", "cashier_id", "sale_date"),
        CheckConstraint("status IN ('completed', 'voided')", name="ck_sales_status"),
        CheckConstraint("total_amount >= 0", name="ck_sales_total"),
        CheckConstraint("sale_type IN ('cash', 'credit')", name="ck_sales_sale_type"),
        CheckConstraint("payment_status IN ('paid', 'pending', 'partial', 'overdue')", name="ck_sales_pay_status"),
    )

    def __repr__(self):
        return f"<Sale {self.invoice_number} ${self.total_amount}>"


class SaleItem(db.Model):
    """Line item within a sale."""

    __tablename__ = "sale_items"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("products.id"), nullable=False)

    product_name = db.Column(db.String(255), nullable=False)
    product_sku = db.Column(db.String(50))
    quantity = db.Column(db.Numeric(12, 4), nullable=False)
    unit_price = db.Column(db.Numeric(18, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(18, 6), nullable=False)
    tax_rate = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    discount_pct = db.Column(db.Numeric(8, 4), nullable=False, default=0)

    subtotal = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False)
    total = db.Column(db.Numeric(18, 2), nullable=False)

    sale = db.relationship("Sale", back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_items_qty"),
        CheckConstraint("unit_price >= 0", name="ck_sale_items_price"),
    )

    def __repr__(self):
        return f"<SaleItem {self.product_name} x{self.quantity}>"


class Payment(db.Model):
    """Payment method used in a sale."""

    __tablename__ = "payments"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)

    method = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    reference = db.Column(db.String(100))
    received_amount = db.Column(db.Numeric(18, 2))
    change_amount = db.Column(db.Numeric(18, 2), default=0)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    sale = db.relationship("Sale", back_populates="payments")

    __table_args__ = (
        CheckConstraint(
            "method IN ('cash', 'card', 'transfer', 'nequi', 'daviplata', 'mixed', 'voucher')", name="ck_pay_method"
        ),
        CheckConstraint("amount > 0", name="ck_pay_amount"),
    )

    def __repr__(self):
        return f"<Payment {self.method} ${self.amount}>"


class CreditNote(db.Model):
    """Partial return / credit note against a sale."""

    __tablename__ = "credit_notes"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    credit_note_number = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    items = db.relationship("CreditNoteItem", back_populates="credit_note", lazy="joined", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("tenant_id", "credit_note_number", name="uq_cn_tenant_number"),)


class CreditNoteItem(db.Model):
    """Item returned in a credit note."""

    __tablename__ = "credit_note_items"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    credit_note_id = db.Column(UUID(as_uuid=True), db.ForeignKey("credit_notes.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("products.id"), nullable=False)
    product_name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Numeric(12, 4), nullable=False)
    unit_price = db.Column(db.Numeric(18, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(18, 6), nullable=False)
    tax_rate = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False)
    total = db.Column(db.Numeric(18, 2), nullable=False)

    credit_note = db.relationship("CreditNote", back_populates="items")
