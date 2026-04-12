"""Order models — Order, OrderItem, OrderStatusHistory."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class Order(db.Model):
    """A pre-sale order (borrador). Does NOT touch accounting until closed."""

    __tablename__ = "orders"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)

    order_number = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    vertical_type = db.Column(db.String(20), nullable=False, default="restaurant")

    # Location / assignment
    table_number = db.Column(db.String(50), nullable=True)
    assigned_to = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    branch_id = db.Column(UUID(as_uuid=True), nullable=True)

    # Customer info (for delivery / catering)
    customer_name = db.Column(db.String(200), nullable=True)
    customer_phone = db.Column(db.String(30), nullable=True)
    delivery_address = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Preview total (NOT contable — just for display)
    total_preview = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    # Link to Sale (filled when CLOSED)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)
    advance_sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)

    # Audit
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    closed_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    cancelled_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    cancel_reason = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    idempotency_key = db.Column(db.String(100), nullable=True, unique=True)

    # Relationships
    items = db.relationship("OrderItem", back_populates="order", lazy="select", cascade="all, delete-orphan")
    history = db.relationship(
        "OrderStatusHistory",
        back_populates="order",
        lazy="dynamic",
        order_by="OrderStatusHistory.changed_at.desc()",
    )

    __table_args__ = (
        Index("idx_orders_tenant_status", "tenant_id", "status"),
        Index("idx_orders_tenant_date", "tenant_id", "created_at"),
        Index("idx_orders_tenant_table", "tenant_id", "table_number"),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'in_preparation', 'ready', " "'closed', 'cancelled', 'close_failed')",
            name="ck_orders_status",
        ),
        CheckConstraint(
            "vertical_type IN ('restaurant', 'cafe', 'drugstore', 'catering')",
            name="ck_orders_vertical",
        ),
        CheckConstraint("total_preview >= 0", name="ck_orders_total"),
    )

    def __repr__(self):
        return f"<Order {self.order_number} [{self.status}]>"

    @property
    def is_active(self):
        return self.status not in ("closed", "cancelled")

    @property
    def is_closable(self):
        return self.status in ("ready", "close_failed")


class OrderItem(db.Model):
    """Line item within an order. Snapshots product data at time of adding."""

    __tablename__ = "order_items"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)

    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("products.id"), nullable=False)
    product_name = db.Column(db.String(255), nullable=False)
    product_sku = db.Column(db.String(50), nullable=True)
    unit_price = db.Column(db.Numeric(18, 2), nullable=False)
    quantity = db.Column(db.Numeric(12, 4), nullable=False)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    notes = db.Column(db.String(255), nullable=True)
    added_after_confirmation = db.Column(db.Boolean, nullable=False, default=False)
    added_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    order = db.relationship("Order", back_populates="items")

    __table_args__ = (
        Index("idx_order_items_order", "order_id"),
        Index("idx_order_items_product", "tenant_id", "product_id"),
        CheckConstraint("quantity > 0", name="ck_oi_qty"),
        CheckConstraint("unit_price >= 0", name="ck_oi_price"),
    )

    def __repr__(self):
        return f"<OrderItem {self.product_name} x{self.quantity}>"


class OrderStatusHistory(db.Model):
    """Immutable audit log of order state transitions."""

    __tablename__ = "order_status_history"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)

    from_status = db.Column(db.String(20), nullable=True)
    to_status = db.Column(db.String(20), nullable=False)
    changed_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    changed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    order = db.relationship("Order", back_populates="history")

    __table_args__ = (Index("idx_osh_order_date", "order_id", "changed_at"),)

    def __repr__(self):
        return f"<OrderHistory {self.from_status} → {self.to_status}>"
