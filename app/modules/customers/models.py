"""Customer models — Customers, Payments, Debit Notes for CxC."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class Customer(db.Model):
    """Customer / client for a tenant."""

    __tablename__ = "customers"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    name = db.Column(db.String(255), nullable=False)
    tax_id = db.Column(db.String(20))
    tax_id_type = db.Column(db.String(10), default="CC")  # CC, NIT, CE, PAS
    contact_name = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    address = db.Column(db.String(500))
    city = db.Column(db.String(100))

    credit_limit = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    credit_days = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at = db.Column(db.DateTime(timezone=True))
    version = db.Column(db.Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("tenant_id", "tax_id", name="uq_customers_tenant_taxid"),
        Index("idx_customers_tenant_name", "tenant_id", "name"),
    )

    def __repr__(self):
        return f"<Customer {self.name}>"


class CustomerPayment(db.Model):
    """Payment received from a customer (abono to credit sale)."""

    __tablename__ = "customer_payments"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=False)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    payment_number = db.Column(db.String(30), nullable=False)
    payment_date = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    payment_method = db.Column(db.String(30), nullable=False, default="cash")
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="completed")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    customer = db.relationship("Customer", backref="payments")

    __table_args__ = (
        UniqueConstraint("tenant_id", "payment_number", name="uq_cp_tenant_number"),
        Index("idx_cp_tenant_customer", "tenant_id", "customer_id"),
        CheckConstraint("amount > 0", name="ck_cp_amount"),
        CheckConstraint("status IN ('completed', 'voided')", name="ck_cp_status"),
    )

    def __repr__(self):
        return f"<CustomerPayment {self.payment_number} ${self.amount}>"


class SalesDebitNote(db.Model):
    """Debit note against a customer (interest, additional charges)."""

    __tablename__ = "sales_debit_notes"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=False)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    note_number = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    customer = db.relationship("Customer", backref="debit_notes")

    __table_args__ = (
        UniqueConstraint("tenant_id", "note_number", name="uq_sdn_tenant_number"),
        CheckConstraint("amount > 0", name="ck_sdn_amount"),
    )

    def __repr__(self):
        return f"<SalesDebitNote {self.note_number}>"


class CollectionCampaign(db.Model):
    """Campaign for collecting overdue receivables."""

    __tablename__ = "collection_campaigns"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    campaign_number = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    target_type = db.Column(db.String(30), nullable=False, default="all_overdue")
    min_days_overdue = db.Column(db.Integer, nullable=False, default=0)
    min_amount_due = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    message_template = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="draft")
    scheduled_date = db.Column(db.DateTime(timezone=True))
    executed_at = db.Column(db.DateTime(timezone=True))

    total_customers = db.Column(db.Integer, nullable=False, default=0)
    total_amount_targeted = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    items = db.relationship(
        "CollectionCampaignItem", back_populates="campaign", lazy="joined", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_number", name="uq_cc_tenant_number"),
        CheckConstraint(
            "target_type IN ('all_overdue', 'by_age', 'by_amount', 'specific_customers')", name="ck_cc_target"
        ),
        CheckConstraint("status IN ('draft', 'active', 'completed', 'cancelled')", name="ck_cc_status"),
    )

    def __repr__(self):
        return f"<CollectionCampaign {self.campaign_number} ({self.status})>"


class CollectionCampaignItem(db.Model):
    """Individual customer within a collection campaign."""

    __tablename__ = "collection_campaign_items"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    campaign_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("collection_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=False)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)

    amount_due = db.Column(db.Numeric(18, 2), nullable=False)
    days_overdue = db.Column(db.Integer, nullable=False, default=0)

    contact_method = db.Column(db.String(20), default="phone_call")
    contact_status = db.Column(db.String(20), nullable=False, default="pending")
    contact_date = db.Column(db.DateTime(timezone=True))
    promise_date = db.Column(db.DateTime(timezone=True))
    rendered_message = db.Column(db.Text)
    notes = db.Column(db.Text)

    campaign = db.relationship("CollectionCampaign", back_populates="items")
    customer = db.relationship("Customer")

    __table_args__ = (
        CheckConstraint("contact_method IN ('sms', 'whatsapp', 'email', 'phone_call')", name="ck_cci_method"),
        CheckConstraint(
            "contact_status IN ('pending', 'contacted', 'promised', 'paid', 'failed')", name="ck_cci_status"
        ),
    )

    def __repr__(self):
        return f"<CampaignItem customer={self.customer_id} status={self.contact_status}>"
