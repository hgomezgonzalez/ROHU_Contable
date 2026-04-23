"""Integration tests for wholesale checkout — ACID sale creation, regression."""

from decimal import Decimal

import pytest


@pytest.mark.integration
class TestWholesaleCheckout:
    """Test checkout flow with wholesale pricing."""

    def test_checkout_wholesale_uses_wholesale_price(
        self, db_session, tenant, admin_user, wholesale_product
    ):
        """TC-WHL-I-001: Checkout in wholesale mode uses wholesale_price."""
        from app.modules.pos.services import create_sale_from_items

        result = create_sale_from_items(
            tenant_id=str(tenant.id),
            created_by=str(admin_user.id),
            items=[{"product_id": str(wholesale_product.id), "quantity": 10, "discount_pct": 0}],
            payments=[{"method": "cash", "amount": 280000, "received_amount": 280000}],
            is_wholesale=True,
            auto_commit=False,
        )

        assert result["is_wholesale"] is True
        item = result["items"][0]
        assert Decimal(str(item["unit_price"])) == Decimal("28000")
        assert item["price_tier"] == "wholesale"
        assert Decimal(str(result["subtotal"])) == Decimal("280000")

    def test_checkout_wholesale_sale_persisted(
        self, db_session, tenant, admin_user, wholesale_product
    ):
        """TC-WHL-I-006: is_wholesale=True persisted in Sale."""
        from app.modules.pos.models import Sale
        from app.modules.pos.services import create_sale_from_items

        result = create_sale_from_items(
            tenant_id=str(tenant.id),
            created_by=str(admin_user.id),
            items=[{"product_id": str(wholesale_product.id), "quantity": 5, "discount_pct": 0}],
            payments=[{"method": "cash", "amount": 140000, "received_amount": 140000}],
            is_wholesale=True,
            auto_commit=False,
        )

        sale = Sale.query.get(result["id"])
        assert sale.is_wholesale is True

    def test_checkout_stock_decremented(
        self, db_session, tenant, admin_user, wholesale_product
    ):
        """TC-WHL-I-005: Stock is correctly decremented in wholesale sale."""
        from app.modules.pos.services import create_sale_from_items

        stock_before = float(wholesale_product.stock_current)

        create_sale_from_items(
            tenant_id=str(tenant.id),
            created_by=str(admin_user.id),
            items=[{"product_id": str(wholesale_product.id), "quantity": 10, "discount_pct": 0}],
            payments=[{"method": "cash", "amount": 280000, "received_amount": 280000}],
            is_wholesale=True,
            auto_commit=False,
        )

        assert float(wholesale_product.stock_current) == stock_before - 10


@pytest.mark.integration
@pytest.mark.regression
class TestWholesaleRegression:
    """Ensure retail sales are NOT affected by wholesale feature."""

    def test_retail_sale_unaffected(
        self, db_session, tenant, admin_user, wholesale_product
    ):
        """TC-WHL-R-001: Retail sale uses sale_price even if wholesale_price exists."""
        from app.modules.pos.services import create_sale_from_items

        result = create_sale_from_items(
            tenant_id=str(tenant.id),
            created_by=str(admin_user.id),
            items=[{"product_id": str(wholesale_product.id), "quantity": 2, "discount_pct": 0}],
            payments=[{"method": "cash", "amount": 70000, "received_amount": 70000}],
            is_wholesale=False,
            auto_commit=False,
        )

        assert result["is_wholesale"] is False
        item = result["items"][0]
        assert Decimal(str(item["unit_price"])) == Decimal("35000")
        assert item["price_tier"] == "retail"

    def test_default_is_retail(
        self, db_session, tenant, admin_user, wholesale_product
    ):
        """TC-WHL-R-005: create_sale_from_items without is_wholesale defaults to retail."""
        from app.modules.pos.services import create_sale_from_items

        result = create_sale_from_items(
            tenant_id=str(tenant.id),
            created_by=str(admin_user.id),
            items=[{"product_id": str(wholesale_product.id), "quantity": 1, "discount_pct": 0}],
            payments=[{"method": "cash", "amount": 35000, "received_amount": 35000}],
            auto_commit=False,
        )

        assert result["is_wholesale"] is False
        assert result["items"][0]["price_tier"] == "retail"

    def test_fallback_when_no_wholesale_price(
        self, db_session, tenant, admin_user, retail_only_product
    ):
        """TC-WHL-E-001: Product without wholesale_price in wholesale mode uses sale_price."""
        from app.modules.pos.services import create_sale_from_items

        result = create_sale_from_items(
            tenant_id=str(tenant.id),
            created_by=str(admin_user.id),
            items=[{"product_id": str(retail_only_product.id), "quantity": 10, "discount_pct": 0}],
            payments=[{"method": "cash", "amount": 5000, "received_amount": 5000}],
            is_wholesale=True,
            auto_commit=False,
        )

        item = result["items"][0]
        assert Decimal(str(item["unit_price"])) == Decimal("500")
        assert item["price_tier"] == "retail"


@pytest.mark.integration
class TestWholesaleInventoryAPI:
    """Test inventory API with wholesale fields."""

    def test_product_serializer_includes_wholesale_fields(self, wholesale_product):
        """TC-WHL-S-002: Product dict includes wholesale fields."""
        from app.modules.inventory.services import _product_to_dict

        d = _product_to_dict(wholesale_product)
        assert d["wholesale_price"] == 28000.0
        assert d["wholesale_min_qty"] == 10.0
        assert d["has_wholesale"] is True

    def test_product_serializer_null_wholesale(self, retail_only_product):
        """Product dict has null wholesale fields when not configured."""
        from app.modules.inventory.services import _product_to_dict

        d = _product_to_dict(retail_only_product)
        assert d["wholesale_price"] is None
        assert d["wholesale_min_qty"] is None
        assert d["has_wholesale"] is False

    def test_update_product_with_wholesale(self, db_session, tenant, wholesale_product):
        """Update product wholesale fields."""
        from app.modules.inventory.services import update_product

        result = update_product(
            str(tenant.id), str(wholesale_product.id),
            wholesale_price=25000, wholesale_min_qty=20,
        )
        assert result["wholesale_price"] == 25000.0
        assert result["wholesale_min_qty"] == 20.0

    def test_remove_wholesale_from_product(self, db_session, tenant, wholesale_product):
        """Remove wholesale pricing from product by setting to None."""
        from app.modules.inventory.services import update_product

        result = update_product(
            str(tenant.id), str(wholesale_product.id),
            wholesale_price=None, wholesale_min_qty=None,
        )
        assert result["wholesale_price"] is None
        assert result["wholesale_min_qty"] is None
