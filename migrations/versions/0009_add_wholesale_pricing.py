"""Add wholesale pricing support to products, sales, sale_items, orders,
order_items.

Revision ID: 0009_wholesale
Revises: 0008_orders
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_wholesale"
down_revision = "0008_orders"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. products: wholesale price fields ──────────────────────
    op.add_column(
        "products",
        sa.Column("wholesale_price", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("wholesale_min_qty", sa.Numeric(12, 4), nullable=True),
    )
    op.create_check_constraint(
        "ck_products_wholesale_consistency",
        "products",
        "(wholesale_price IS NULL AND wholesale_min_qty IS NULL) "
        "OR (wholesale_price IS NOT NULL AND wholesale_min_qty IS NOT NULL "
        "AND wholesale_price >= 0 AND wholesale_min_qty >= 1)",
    )
    op.create_index(
        "idx_products_has_wholesale",
        "products",
        ["tenant_id"],
        postgresql_where=sa.text("wholesale_price IS NOT NULL AND deleted_at IS NULL"),
    )

    # ── 2. sales: is_wholesale flag ───────────────────────────────
    op.add_column(
        "sales",
        sa.Column(
            "is_wholesale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "idx_sales_tenant_wholesale",
        "sales",
        ["tenant_id", "is_wholesale", "sale_date"],
        postgresql_where=sa.text("is_wholesale = true"),
    )

    # ── 3. sale_items: price_tier snapshot ────────────────────────
    op.add_column(
        "sale_items",
        sa.Column(
            "price_tier",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'retail'"),
        ),
    )
    op.create_check_constraint(
        "ck_sale_items_price_tier",
        "sale_items",
        "price_tier IN ('retail', 'wholesale')",
    )

    # ── 4. orders: is_wholesale flag ──────────────────────────────
    op.add_column(
        "orders",
        sa.Column(
            "is_wholesale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "idx_orders_tenant_wholesale",
        "orders",
        ["tenant_id", "is_wholesale", "created_at"],
        postgresql_where=sa.text("is_wholesale = true"),
    )

    # ── 5. order_items: price_tier snapshot ───────────────────────
    op.add_column(
        "order_items",
        sa.Column(
            "price_tier",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'retail'"),
        ),
    )
    op.create_check_constraint(
        "ck_order_items_price_tier",
        "order_items",
        "price_tier IN ('retail', 'wholesale')",
    )


def downgrade():
    # order_items
    op.drop_constraint("ck_order_items_price_tier", "order_items", type_="check")
    op.drop_column("order_items", "price_tier")

    # orders
    op.drop_index("idx_orders_tenant_wholesale", table_name="orders")
    op.drop_column("orders", "is_wholesale")

    # sale_items
    op.drop_constraint("ck_sale_items_price_tier", "sale_items", type_="check")
    op.drop_column("sale_items", "price_tier")

    # sales
    op.drop_index("idx_sales_tenant_wholesale", table_name="sales")
    op.drop_column("sales", "is_wholesale")

    # products
    op.drop_index("idx_products_has_wholesale", table_name="products")
    op.drop_constraint("ck_products_wholesale_consistency", "products", type_="check")
    op.drop_column("products", "wholesale_min_qty")
    op.drop_column("products", "wholesale_price")
