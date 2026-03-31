"""Inventory models — Products, Categories, Stock Movements."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class Category(db.Model):
    """Product category within a tenant."""

    __tablename__ = "categories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    parent_id = db.Column(UUID(as_uuid=True), db.ForeignKey("categories.id"), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    tax_type = db.Column(db.String(20), nullable=False, default="iva_19")
    tax_rate = db.Column(db.Numeric(8, 4), nullable=False, default=19.0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    version = db.Column(db.Integer, nullable=False, default=1)

    products = db.relationship("Product", back_populates="category", lazy="dynamic")
    children = db.relationship("Category", back_populates="parent", lazy="dynamic")
    parent = db.relationship("Category", remote_side=[id], back_populates="children")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "parent_id", name="uq_categories_tenant_name_parent"),
        CheckConstraint("tax_type IN ('iva_19', 'iva_5', 'exempt', 'excluded')", name="ck_categories_tax_type"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_categories_tax_rate"),
    )

    def __repr__(self):
        return f"<Category {self.name}>"


class Product(db.Model):
    """Product in a tenant's catalog."""

    __tablename__ = "products"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    category_id = db.Column(UUID(as_uuid=True), db.ForeignKey("categories.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    sku = db.Column(db.String(50))
    qr_code = db.Column(db.String(100))
    barcode = db.Column(db.String(100))
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    unit = db.Column(db.String(20), nullable=False, default="unit")

    purchase_price = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    sale_price = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    cost_average = db.Column(db.Numeric(18, 6), nullable=False, default=0)

    tax_type = db.Column(db.String(20), nullable=False, default="iva_19")
    tax_rate = db.Column(db.Numeric(8, 4), nullable=False, default=19.0)

    stock_current = db.Column(db.Numeric(12, 4), nullable=False, default=0)
    stock_minimum = db.Column(db.Numeric(12, 4), nullable=False, default=0)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_draft = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at = db.Column(db.DateTime(timezone=True))
    version = db.Column(db.Integer, nullable=False, default=1)

    category = db.relationship("Category", back_populates="products")
    movements = db.relationship("StockMovement", back_populates="product", lazy="dynamic")

    __table_args__ = (
        UniqueConstraint("tenant_id", "qr_code", name="uq_products_tenant_qr"),
        UniqueConstraint("tenant_id", "barcode", name="uq_products_tenant_barcode"),
        UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        Index("idx_products_tenant_name", "tenant_id", "name"),
        Index("idx_products_tenant_active", "tenant_id", "is_active"),
        CheckConstraint("sale_price >= 0", name="ck_products_sale_price"),
        CheckConstraint("purchase_price >= 0", name="ck_products_purchase_price"),
        CheckConstraint("tax_type IN ('iva_19', 'iva_5', 'exempt', 'excluded')", name="ck_products_tax_type"),
        CheckConstraint("unit IN ('unit', 'kg', 'g', 'lt', 'ml', 'box', 'pack', 'meter')", name="ck_products_unit"),
    )

    @property
    def is_low_stock(self):
        return self.stock_current <= self.stock_minimum

    def __repr__(self):
        return f"<Product {self.name} ({self.sku})>"


class StockMovement(db.Model):
    """Tracks every stock change for audit and traceability."""

    __tablename__ = "stock_movements"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("products.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    movement_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Numeric(12, 4), nullable=False)
    stock_before = db.Column(db.Numeric(12, 4), nullable=False)
    stock_after = db.Column(db.Numeric(12, 4), nullable=False)
    unit_cost = db.Column(db.Numeric(18, 6), nullable=False, default=0)

    reference_type = db.Column(db.String(50))
    reference_id = db.Column(UUID(as_uuid=True))
    reason = db.Column(db.String(255))

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    product = db.relationship("Product", back_populates="movements")

    __table_args__ = (
        Index("idx_movements_tenant_product", "tenant_id", "product_id", "created_at"),
        Index("idx_movements_reference", "reference_type", "reference_id"),
        CheckConstraint(
            "movement_type IN ('initial_stock', 'sale', 'purchase_receipt', "
            "'adjustment_positive', 'adjustment_negative', 'return_sale', "
            "'return_purchase', 'transfer_in', 'transfer_out')",
            name="ck_movements_type"
        ),
    )

    def __repr__(self):
        return f"<StockMovement {self.movement_type} qty={self.quantity}>"


class InventoryAdjustment(db.Model):
    """Batch inventory adjustment with approval workflow."""

    __tablename__ = "inventory_adjustments"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)

    adjustment_number = db.Column(db.String(30), nullable=False)
    adjustment_type = db.Column(db.String(20), nullable=False, default="physical_count")
    status = db.Column(db.String(20), nullable=False, default="draft")
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    approved_at = db.Column(db.DateTime(timezone=True))

    items = db.relationship("InventoryAdjustmentItem", back_populates="adjustment",
                            lazy="joined", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "adjustment_number", name="uq_ia_tenant_number"),
        CheckConstraint(
            "adjustment_type IN ('physical_count', 'damage', 'loss', 'donation')",
            name="ck_ia_type"
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected')",
            name="ck_ia_status"
        ),
    )

    def __repr__(self):
        return f"<InventoryAdjustment {self.adjustment_number} ({self.status})>"


class InventoryAdjustmentItem(db.Model):
    """Item within a batch inventory adjustment."""

    __tablename__ = "inventory_adjustment_items"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    adjustment_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("inventory_adjustments.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("products.id"), nullable=False)

    product_name = db.Column(db.String(255), nullable=False)
    stock_system = db.Column(db.Numeric(12, 4), nullable=False)
    stock_counted = db.Column(db.Numeric(12, 4), nullable=False)
    difference = db.Column(db.Numeric(12, 4), nullable=False)
    unit_cost = db.Column(db.Numeric(18, 6), nullable=False)
    total_cost = db.Column(db.Numeric(18, 2), nullable=False)

    adjustment = db.relationship("InventoryAdjustment", back_populates="items")

    def __repr__(self):
        return f"<IAItem {self.product_name} diff={self.difference}>"


class DiscountPolicy(db.Model):
    """Discount limits per role for POS checkout."""

    __tablename__ = "discount_policies"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    role_id = db.Column(UUID(as_uuid=True), db.ForeignKey("roles.id"), nullable=False)

    max_discount_pct = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    requires_approval_above = db.Column(db.Numeric(8, 4), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "role_id", name="uq_dp_tenant_role"),
        CheckConstraint("max_discount_pct >= 0 AND max_discount_pct <= 100", name="ck_dp_max"),
    )

    def __repr__(self):
        return f"<DiscountPolicy max={self.max_discount_pct}%>"
