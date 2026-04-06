"""Purchases models — Suppliers, Purchase Orders, PO Items."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class Supplier(db.Model):
    """Supplier / vendor for a tenant."""

    __tablename__ = "suppliers"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    name = db.Column(db.String(255), nullable=False)
    tax_id = db.Column(db.String(20))
    contact_name = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    address = db.Column(db.String(500))
    city = db.Column(db.String(100))
    payment_terms_days = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at = db.Column(db.DateTime(timezone=True))
    version = db.Column(db.Integer, nullable=False, default=1)

    purchase_orders = db.relationship("PurchaseOrder", back_populates="supplier", lazy="dynamic")

    __table_args__ = (
        UniqueConstraint("tenant_id", "tax_id", name="uq_suppliers_tenant_taxid"),
        Index("idx_suppliers_tenant_name", "tenant_id", "name"),
    )

    def __repr__(self):
        return f"<Supplier {self.name}>"


class PurchaseOrder(db.Model):
    """Purchase order to a supplier."""

    __tablename__ = "purchase_orders"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    supplier_id = db.Column(UUID(as_uuid=True), db.ForeignKey("suppliers.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    order_number = db.Column(db.String(30), nullable=False)
    order_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    expected_date = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(20), nullable=False, default="draft")
    payment_type = db.Column(db.String(20), nullable=False, default="cash")

    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    supplier_invoice = db.Column(db.String(50))
    notes = db.Column(db.Text)

    received_at = db.Column(db.DateTime(timezone=True))
    received_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))
    cancelled_at = db.Column(db.DateTime(timezone=True))

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    version = db.Column(db.Integer, nullable=False, default=1)

    supplier = db.relationship("Supplier", back_populates="purchase_orders")
    items = db.relationship("PurchaseOrderItem", back_populates="order", lazy="joined", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "order_number", name="uq_po_tenant_number"),
        Index("idx_po_tenant_status", "tenant_id", "status"),
        Index("idx_po_tenant_date", "tenant_id", "order_date"),
        CheckConstraint(
            "status IN ('draft', 'sent', 'received', 'partially_received', 'cancelled')", name="ck_po_status"
        ),
        CheckConstraint("payment_type IN ('cash', 'credit')", name="ck_po_payment_type"),
    )

    def __repr__(self):
        return f"<PO {self.order_number} ({self.status})>"


class PurchaseOrderItem(db.Model):
    """Line item within a purchase order."""

    __tablename__ = "purchase_order_items"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("products.id"), nullable=False)

    product_name = db.Column(db.String(255), nullable=False)
    quantity_ordered = db.Column(db.Numeric(12, 4), nullable=False)
    quantity_received = db.Column(db.Numeric(12, 4), nullable=False, default=0)
    unit_cost = db.Column(db.Numeric(18, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(8, 4), nullable=False, default=19.0)

    subtotal = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False)
    total = db.Column(db.Numeric(18, 2), nullable=False)

    order = db.relationship("PurchaseOrder", back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_poi_qty"),
        CheckConstraint("quantity_received >= 0", name="ck_poi_received"),
        CheckConstraint("unit_cost >= 0", name="ck_poi_cost"),
    )

    def __repr__(self):
        return f"<POItem {self.product_name} x{self.quantity_ordered}>"


class SupplierPayment(db.Model):
    """Payment to a supplier (CxP settlement)."""

    __tablename__ = "supplier_payments"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    supplier_id = db.Column(UUID(as_uuid=True), db.ForeignKey("suppliers.id"), nullable=False)
    purchase_order_id = db.Column(UUID(as_uuid=True), db.ForeignKey("purchase_orders.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    payment_number = db.Column(db.String(30), nullable=False)
    payment_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    payment_method = db.Column(db.String(30), nullable=False, default="cash")
    reference = db.Column(db.String(100))
    bank_account = db.Column(db.String(50))
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="completed")
    voided_at = db.Column(db.DateTime(timezone=True))
    voided_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    supplier = db.relationship("Supplier", backref="payments")

    __table_args__ = (
        UniqueConstraint("tenant_id", "payment_number", name="uq_sp_tenant_number"),
        Index("idx_sp_tenant_supplier", "tenant_id", "supplier_id"),
        CheckConstraint("amount > 0", name="ck_sp_amount"),
        CheckConstraint("payment_method IN ('cash', 'transfer', 'check', 'nequi', 'daviplata')", name="ck_sp_method"),
        CheckConstraint("status IN ('completed', 'voided')", name="ck_sp_status"),
    )

    def __repr__(self):
        return f"<SupplierPayment {self.payment_number} ${self.amount}>"


class PurchaseCreditNote(db.Model):
    """Credit note for a purchase (return to supplier)."""

    __tablename__ = "purchase_credit_notes"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    supplier_id = db.Column(UUID(as_uuid=True), db.ForeignKey("suppliers.id"), nullable=False)
    purchase_order_id = db.Column(UUID(as_uuid=True), db.ForeignKey("purchase_orders.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    note_number = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    supplier = db.relationship("Supplier", backref="credit_notes")
    items = db.relationship(
        "PurchaseCreditNoteItem", back_populates="credit_note", lazy="joined", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "note_number", name="uq_pcn_tenant_number"),
        Index("idx_pcn_tenant_supplier", "tenant_id", "supplier_id"),
    )

    def __repr__(self):
        return f"<PurchaseCreditNote {self.note_number}>"


class PurchaseCreditNoteItem(db.Model):
    """Line item within a purchase credit note."""

    __tablename__ = "purchase_credit_note_items"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    credit_note_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("purchase_credit_notes.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("products.id"), nullable=False)

    product_name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Numeric(12, 4), nullable=False)
    unit_cost = db.Column(db.Numeric(18, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(8, 4), nullable=False, default=19.0)

    subtotal = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False)
    total = db.Column(db.Numeric(18, 2), nullable=False)

    credit_note = db.relationship("PurchaseCreditNote", back_populates="items")

    def __repr__(self):
        return f"<PCNItem {self.product_name} x{self.quantity}>"


class PurchaseDebitNote(db.Model):
    """Debit note for a purchase (additional charges from supplier)."""

    __tablename__ = "purchase_debit_notes"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    supplier_id = db.Column(UUID(as_uuid=True), db.ForeignKey("suppliers.id"), nullable=False)
    purchase_order_id = db.Column(UUID(as_uuid=True), db.ForeignKey("purchase_orders.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    note_number = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    supplier = db.relationship("Supplier", backref="debit_notes")

    __table_args__ = (
        UniqueConstraint("tenant_id", "note_number", name="uq_pdn_tenant_number"),
        CheckConstraint("amount > 0", name="ck_pdn_amount"),
    )

    def __repr__(self):
        return f"<PurchaseDebitNote {self.note_number}>"
