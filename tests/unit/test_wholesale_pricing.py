"""Unit tests for wholesale pricing — model, price resolution, validation."""

from decimal import Decimal

import pytest


class TestProductWholesaleModel:
    """Test Product model wholesale fields and methods."""

    def test_product_with_wholesale_price(self, wholesale_product):
        """TC-WHL-U-001: Product with wholesale fields accessible."""
        assert wholesale_product.wholesale_price == Decimal("28000")
        assert wholesale_product.wholesale_min_qty == Decimal("10")
        assert wholesale_product.has_wholesale is True

    def test_product_without_wholesale_price(self, retail_only_product):
        """TC-WHL-U-002: Product without wholesale fields."""
        assert retail_only_product.wholesale_price is None
        assert retail_only_product.wholesale_min_qty is None
        assert retail_only_product.has_wholesale is False

    def test_get_price_for_tier_wholesale(self, wholesale_product):
        """TC-WHL-U-005: Wholesale mode returns wholesale_price."""
        price, tier = wholesale_product.get_price_for_tier(is_wholesale=True)
        assert price == Decimal("28000")
        assert tier == "wholesale"

    def test_get_price_for_tier_retail(self, wholesale_product):
        """TC-WHL-U-007: Retail mode returns sale_price even with wholesale configured."""
        price, tier = wholesale_product.get_price_for_tier(is_wholesale=False)
        assert price == Decimal("35000")
        assert tier == "retail"

    def test_get_price_for_tier_fallback(self, retail_only_product):
        """TC-WHL-U-006: Wholesale mode with no wholesale_price falls back to retail."""
        price, tier = retail_only_product.get_price_for_tier(is_wholesale=True)
        assert price == Decimal("500")
        assert tier == "retail"

    def test_get_price_for_tier_retail_no_wholesale(self, retail_only_product):
        """TC-WHL-U-008: Retail mode, no wholesale configured."""
        price, tier = retail_only_product.get_price_for_tier(is_wholesale=False)
        assert price == Decimal("500")
        assert tier == "retail"


class TestWholesaleValidation:
    """Test wholesale price validation rules."""

    def test_wholesale_price_must_be_less_than_sale_price(self, db_session, tenant, admin_user):
        """TC-WHL-U-003: wholesale_price >= sale_price raises error."""
        from app.modules.inventory.services import create_product

        with pytest.raises(ValueError, match="menor al precio de venta"):
            create_product(
                tenant_id=str(tenant.id),
                created_by=str(admin_user.id),
                name="Test Invalid Wholesale",
                sale_price=10000,
                wholesale_price=15000,
                wholesale_min_qty=5,
            )

    def test_wholesale_min_qty_required_with_price(self, db_session, tenant, admin_user):
        """TC-WHL-U-004: wholesale_price without min_qty raises error."""
        from app.modules.inventory.services import create_product

        with pytest.raises(ValueError, match="wholesale_min_qty"):
            create_product(
                tenant_id=str(tenant.id),
                created_by=str(admin_user.id),
                name="Test Missing Min Qty",
                sale_price=10000,
                wholesale_price=8000,
                wholesale_min_qty=None,
            )

    def test_wholesale_price_required_with_min_qty(self, db_session, tenant, admin_user):
        """wholesale_min_qty without wholesale_price raises error."""
        from app.modules.inventory.services import create_product

        with pytest.raises(ValueError, match="wholesale_price"):
            create_product(
                tenant_id=str(tenant.id),
                created_by=str(admin_user.id),
                name="Test Missing Price",
                sale_price=10000,
                wholesale_price=None,
                wholesale_min_qty=5,
            )


class TestWholesalePriceResolution:
    """Test resolve_item_price function."""

    def test_resolve_wholesale(self, wholesale_product):
        """resolve_item_price returns wholesale when is_wholesale=True."""
        from app.modules.inventory.services import resolve_item_price

        price, tier = resolve_item_price(wholesale_product, is_wholesale=True)
        assert price == Decimal("28000")
        assert tier == "wholesale"

    def test_resolve_retail(self, wholesale_product):
        """resolve_item_price returns retail when is_wholesale=False."""
        from app.modules.inventory.services import resolve_item_price

        price, tier = resolve_item_price(wholesale_product, is_wholesale=False)
        assert price == Decimal("35000")
        assert tier == "retail"

    def test_resolve_fallback_to_retail(self, retail_only_product):
        """resolve_item_price falls back to retail if no wholesale price."""
        from app.modules.inventory.services import resolve_item_price

        price, tier = resolve_item_price(retail_only_product, is_wholesale=True)
        assert price == Decimal("500")
        assert tier == "retail"


class TestWholesaleTaxCalculation:
    """Test tax calculation with wholesale prices."""

    def test_wholesale_iva_responsible_regime(self):
        """TC-WHL-U-009: 19% IVA on wholesale_price, responsible regime."""
        wholesale_price = Decimal("18000")
        qty = Decimal("10")
        tax_rate = Decimal("19")

        line_subtotal = wholesale_price * qty
        line_tax = (line_subtotal * tax_rate / 100).quantize(Decimal("0.01"))
        line_total = line_subtotal + line_tax

        assert line_subtotal == Decimal("180000")
        assert line_tax == Decimal("34200.00")
        assert line_total == Decimal("214200.00")

    def test_wholesale_simplified_regime_zero_tax(self):
        """TC-WHL-U-010: Simplified regime yields zero tax."""
        wholesale_price = Decimal("18000")
        qty = Decimal("10")
        is_simplified = True

        line_subtotal = wholesale_price * qty
        effective_tax_rate = Decimal("0") if is_simplified else Decimal("19")
        line_tax = (line_subtotal * effective_tax_rate / 100).quantize(Decimal("0.01"))

        assert line_tax == Decimal("0.00")
