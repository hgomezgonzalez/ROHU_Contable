"""Add orders module: orders, order_items, order_status_history tables.
Add orders_config JSONB to tenants, source_order_id to sales.

Revision ID: 0008_orders
Revises: 0007_vouchers
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0008_orders"
down_revision = "0007_vouchers"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. orders_config JSONB on tenants ─────────────────────────
    op.add_column(
        "tenants",
        sa.Column(
            "orders_config",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(
                """'{
                "enabled": false,
                "vertical_type": null,
                "kds_enabled": false,
                "tables_enabled": false,
                "delivery_address_required": false,
                "max_open_orders": 50,
                "trial_started_at": null,
                "addon_active_until": null
            }'::jsonb"""
            ),
        ),
    )

    # ── 2. source_order_id on sales ───────────────────────────────
    op.add_column("sales", sa.Column("source_order_id", UUID(as_uuid=True), nullable=True))

    # ── 3. orders table ───────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("order_number", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("vertical_type", sa.String(20), nullable=False, server_default="restaurant"),
        sa.Column("table_number", sa.String(50), nullable=True),
        sa.Column("assigned_to", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("branch_id", UUID(as_uuid=True), nullable=True),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("customer_phone", sa.String(30), nullable=True),
        sa.Column("delivery_address", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("total_preview", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("sale_id", UUID(as_uuid=True), sa.ForeignKey("sales.id"), nullable=True),
        sa.Column("advance_sale_id", UUID(as_uuid=True), sa.ForeignKey("sales.id"), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("closed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancelled_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancel_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True, unique=True),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'in_preparation', 'ready', "
            "'closed', 'cancelled', 'close_failed')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint(
            "vertical_type IN ('restaurant', 'cafe', 'drugstore', 'catering')",
            name="ck_orders_vertical",
        ),
        sa.CheckConstraint("total_preview >= 0", name="ck_orders_total"),
    )

    # Indices for orders
    op.create_index("idx_orders_tenant_status", "orders", ["tenant_id", "status"])
    op.create_index("idx_orders_tenant_date", "orders", ["tenant_id", sa.text("created_at DESC")])
    op.create_index("idx_orders_tenant_table", "orders", ["tenant_id", "table_number"])

    # FK from sales.source_order_id → orders.id (created after orders table exists)
    op.create_foreign_key("fk_sales_source_order", "sales", "orders", ["source_order_id"], ["id"])
    op.create_index("idx_sales_source_order", "sales", ["source_order_id"])

    # ── 4. order_items table ──────────────────────────────────────
    op.create_table(
        "order_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("product_sku", sa.String(50), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 4), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("notes", sa.String(255), nullable=True),
        sa.Column("added_after_confirmation", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("quantity > 0", name="ck_oi_qty"),
        sa.CheckConstraint("unit_price >= 0", name="ck_oi_price"),
    )
    op.create_index("idx_order_items_order", "order_items", ["order_id"])
    op.create_index("idx_order_items_product", "order_items", ["tenant_id", "product_id"])

    # ── 5. order_status_history table ─────────────────────────────
    op.create_table(
        "order_status_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("changed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_osh_order_date", "order_status_history", ["order_id", sa.text("changed_at DESC")])


def downgrade():
    op.drop_table("order_status_history")
    op.drop_table("order_items")
    op.drop_index("idx_sales_source_order", "sales")
    op.drop_constraint("fk_sales_source_order", "sales", type_="foreignkey")
    op.drop_table("orders")
    op.drop_column("sales", "source_order_id")
    op.drop_column("tenants", "orders_config")
