"""Inventory services — Public interface for the inventory module."""

from decimal import Decimal
from typing import Optional

from sqlalchemy import or_

from app.extensions import db
from app.modules.inventory.models import Category, Product, StockMovement


# ── Category Services ─────────────────────────────────────────────

def create_category(
    tenant_id: str, name: str, tax_type: str = "iva_19",
    parent_id: Optional[str] = None,
) -> dict:
    """Create a product category."""
    tax_rates = {"iva_19": Decimal("19.0"), "iva_5": Decimal("5.0"),
                 "exempt": Decimal("0"), "excluded": Decimal("0")}

    cat = Category(
        tenant_id=tenant_id, name=name, tax_type=tax_type,
        tax_rate=tax_rates.get(tax_type, Decimal("19.0")),
        parent_id=parent_id,
    )
    db.session.add(cat)
    db.session.commit()
    return _category_to_dict(cat)


def get_categories(tenant_id: str) -> list:
    """List all active categories for a tenant."""
    cats = Category.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).order_by(Category.name).all()
    return [_category_to_dict(c) for c in cats]


# ── Product Services ──────────────────────────────────────────────

VALID_TAX_TYPES = {"iva_19", "iva_5", "exempt", "excluded"}
TAX_RATES = {"iva_19": Decimal("19.0"), "iva_5": Decimal("5.0"),
             "exempt": Decimal("0"), "excluded": Decimal("0")}


def _normalize_tax_type(tax_type: str) -> str:
    """Normalize tax_type to valid DB value."""
    if tax_type in VALID_TAX_TYPES:
        return tax_type
    mapping = {"exento": "exempt", "excluido": "excluded", "19": "iva_19", "5": "iva_5"}
    return mapping.get(tax_type.lower(), "iva_19")


def create_product(
    tenant_id: str, created_by: str, name: str, sale_price: float,
    purchase_price: float = 0, qr_code: Optional[str] = None,
    barcode: Optional[str] = None, sku: Optional[str] = None,
    category_id: Optional[str] = None, unit: str = "unit",
    tax_type: str = "iva_19", stock_minimum: float = 0,
    initial_stock: float = 0, description: str = "",
) -> dict:
    """Create a product and optionally set initial stock."""
    tax_type = _normalize_tax_type(tax_type)
    tax_rates = TAX_RATES

    product = Product(
        tenant_id=tenant_id, created_by=created_by, name=name,
        sale_price=Decimal(str(sale_price)),
        purchase_price=Decimal(str(purchase_price)),
        cost_average=Decimal(str(purchase_price)),
        qr_code=qr_code, barcode=barcode, sku=sku,
        category_id=category_id, unit=unit,
        tax_type=tax_type, tax_rate=tax_rates.get(tax_type, Decimal("19.0")),
        stock_minimum=Decimal(str(stock_minimum)),
        description=description,
    )
    db.session.add(product)
    db.session.flush()

    if initial_stock > 0:
        _record_movement(
            product=product, tenant_id=tenant_id, created_by=created_by,
            movement_type="initial_stock",
            quantity=Decimal(str(initial_stock)),
            unit_cost=Decimal(str(purchase_price)),
        )
        # Generate accounting entry for initial stock (DB Inventory / CR Equity)
        inv_value = float(Decimal(str(initial_stock)) * Decimal(str(purchase_price)))
        if inv_value > 0:
            try:
                from app.modules.accounting.services import create_journal_entry
                create_journal_entry(
                    tenant_id=tenant_id, created_by=created_by,
                    entry_type="ADJUSTMENT",
                    description=f"Stock inicial: {name} ({initial_stock} uds × ${purchase_price:,.0f})",
                    lines=[
                        {"puc_code": "1435", "debit": inv_value, "credit": 0,
                         "description": f"Inventario inicial {name}"},
                        {"puc_code": "3115", "debit": 0, "credit": inv_value,
                         "description": "Aporte en especie (inventario)"},
                    ],
                    source_document_type="product_initial_stock",
                    source_document_id=str(product.id),
                )
            except Exception:
                pass  # Don't block product creation if accounting fails

    db.session.commit()
    return _product_to_dict(product)


def update_product(tenant_id: str, product_id: str, **kwargs) -> dict:
    """Update a product's attributes."""
    product = Product.query.filter_by(
        id=product_id, tenant_id=tenant_id
    ).first()
    if not product:
        raise ValueError("Producto no encontrado")

    allowed = {"name", "sale_price", "purchase_price", "qr_code", "barcode",
               "sku", "category_id", "unit", "tax_type", "stock_minimum",
               "description", "is_active"}

    for key, value in kwargs.items():
        if key in allowed and value is not None:
            if key in ("sale_price", "purchase_price", "stock_minimum"):
                value = Decimal(str(value))
            setattr(product, key, value)

    # Sync cost_average with purchase_price when manually edited
    if "purchase_price" in kwargs and kwargs["purchase_price"] is not None:
        product.cost_average = Decimal(str(kwargs["purchase_price"]))

    db.session.commit()
    return _product_to_dict(product)


def get_product_by_qr(tenant_id: str, qr_code: str) -> Optional[dict]:
    """Lookup a product by QR code. Used by POS scanner. Must be fast."""
    product = Product.query.filter_by(
        tenant_id=tenant_id, qr_code=qr_code, is_active=True
    ).first()
    if not product or product.deleted_at:
        return None
    return _product_to_dict(product)


def get_product_by_id(tenant_id: str, product_id: str) -> Optional[dict]:
    """Get a product by ID."""
    product = Product.query.filter_by(
        id=product_id, tenant_id=tenant_id
    ).first()
    if not product or product.deleted_at:
        return None
    return _product_to_dict(product)


def search_products(
    tenant_id: str, query: str = "", page: int = 1, per_page: int = 20,
    category_id: Optional[str] = None, low_stock_only: bool = False,
) -> dict:
    """Search products by name, SKU, QR code or barcode."""
    q = Product.query.filter(
        Product.tenant_id == tenant_id,
        Product.is_active.is_(True),
        Product.deleted_at.is_(None),
    )

    if query:
        import re
        safe = re.sub(r'([%_\\])', r'\\\1', query)
        term = f"%{safe}%"
        q = q.filter(or_(
            Product.name.ilike(term),
            Product.sku.ilike(term),
            Product.qr_code.ilike(term),
            Product.barcode.ilike(term),
        ))

    if category_id:
        q = q.filter(Product.category_id == category_id)

    if low_stock_only:
        q = q.filter(Product.stock_current <= Product.stock_minimum)

    total = q.count()
    products = q.order_by(Product.name).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return {
        "data": [_product_to_dict(p) for p in products],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "has_next": page * per_page < total,
        },
    }


# ── Stock Services ────────────────────────────────────────────────

def check_stock(tenant_id: str, product_id: str, qty: float) -> dict:
    """Check if sufficient stock is available."""
    product = Product.query.filter_by(
        id=product_id, tenant_id=tenant_id
    ).first()
    if not product:
        raise ValueError("Producto no encontrado")

    available = float(product.stock_current)
    return {
        "product_id": str(product.id),
        "available": available,
        "requested": qty,
        "sufficient": available >= qty,
    }


def move_stock(
    tenant_id: str, product_id: str, created_by: str,
    quantity: float, movement_type: str,
    reference_type: str = None, reference_id: str = None,
    reason: str = None, unit_cost: float = 0,
) -> dict:
    """Record a stock movement and update product stock. Returns movement data."""
    product = Product.query.filter_by(
        id=product_id, tenant_id=tenant_id
    ).with_for_update().first()

    if not product:
        raise ValueError("Producto no encontrado")

    movement = _record_movement(
        product=product, tenant_id=tenant_id, created_by=created_by,
        movement_type=movement_type,
        quantity=Decimal(str(quantity)),
        unit_cost=Decimal(str(unit_cost)),
        reference_type=reference_type, reference_id=reference_id,
        reason=reason,
    )

    db.session.commit()
    return _movement_to_dict(movement)


def adjust_stock(
    tenant_id: str, product_id: str, created_by: str,
    new_quantity: float, reason: str,
) -> dict:
    """Adjust stock to a specific quantity (physical count)."""
    product = Product.query.filter_by(
        id=product_id, tenant_id=tenant_id
    ).with_for_update().first()

    if not product:
        raise ValueError("Producto no encontrado")

    diff = Decimal(str(new_quantity)) - product.stock_current
    if diff == 0:
        return _product_to_dict(product)

    movement_type = "adjustment_positive" if diff > 0 else "adjustment_negative"

    _record_movement(
        product=product, tenant_id=tenant_id, created_by=created_by,
        movement_type=movement_type,
        quantity=abs(diff),
        unit_cost=product.cost_average,
        reason=reason,
    )

    # Auto-post accounting entry for inventory adjustments
    cost = (abs(diff) * product.cost_average).quantize(Decimal("0.01"))
    if cost > 0:
        from app.modules.accounting.services import create_journal_entry
        if movement_type == "adjustment_positive":
            # Sobrante: DB 1435 Inventario | CR 4210 Ingresos no operacionales
            lines = [
                {"puc_code": "1435", "debit": float(cost), "credit": 0,
                 "description": f"Ajuste positivo {product.name}: {reason}"},
                {"puc_code": "4210", "debit": 0, "credit": float(cost),
                 "description": "Sobrante inventario"},
            ]
        else:
            # Faltante/merma: DB 5195 Gastos diversos | CR 1435 Inventario
            lines = [
                {"puc_code": "5195", "debit": float(cost), "credit": 0,
                 "description": f"Ajuste negativo {product.name}: {reason}"},
                {"puc_code": "1435", "debit": 0, "credit": float(cost),
                 "description": "Merma/faltante inventario"},
            ]
        create_journal_entry(
            tenant_id=tenant_id, created_by=created_by,
            entry_type="ADJUSTMENT",
            description=f"Ajuste inventario: {product.name} - {reason}",
            lines=lines,
            source_document_type="stock_adjustment",
            source_document_id=str(product.id),
        )

    db.session.commit()
    return _product_to_dict(product)


def get_stock_levels(
    tenant_id: str, low_stock_only: bool = False,
) -> list:
    """Get stock levels for all active products."""
    q = Product.query.filter(
        Product.tenant_id == tenant_id,
        Product.is_active.is_(True),
        Product.deleted_at.is_(None),
    )
    if low_stock_only:
        q = q.filter(Product.stock_current <= Product.stock_minimum)

    products = q.order_by(Product.name).all()
    return [_stock_level_to_dict(p) for p in products]


def get_movements(
    tenant_id: str, product_id: str = None,
    page: int = 1, per_page: int = 50,
) -> dict:
    """Get stock movement history."""
    q = StockMovement.query.filter_by(tenant_id=tenant_id)
    if product_id:
        q = q.filter_by(product_id=product_id)

    total = q.count()
    movements = q.order_by(
        StockMovement.created_at.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "data": [_movement_to_dict(m) for m in movements],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "has_next": page * per_page < total,
        },
    }


# ── Internal Helpers ──────────────────────────────────────────────

def _record_movement(
    product: Product, tenant_id: str, created_by: str,
    movement_type: str, quantity: Decimal, unit_cost: Decimal = Decimal("0"),
    reference_type: str = None, reference_id: str = None, reason: str = None,
) -> StockMovement:
    """Internal: record a movement and update product stock."""
    stock_before = product.stock_current

    # Determine direction
    inbound = movement_type in (
        "initial_stock", "purchase_receipt", "adjustment_positive",
        "return_sale", "transfer_in",
    )

    if inbound:
        product.stock_current += quantity
        # Update cost average (weighted average)
        if unit_cost > 0 and product.stock_current > 0:
            total_value = (stock_before * product.cost_average) + (quantity * unit_cost)
            product.cost_average = total_value / product.stock_current
    else:
        product.stock_current -= quantity

    movement = StockMovement(
        tenant_id=tenant_id, product_id=product.id, created_by=created_by,
        movement_type=movement_type, quantity=quantity,
        stock_before=stock_before, stock_after=product.stock_current,
        unit_cost=unit_cost,
        reference_type=reference_type, reference_id=reference_id,
        reason=reason,
    )
    db.session.add(movement)
    return movement


# ── Serializers ───────────────────────────────────────────────────

def _category_to_dict(cat: Category) -> dict:
    return {
        "id": str(cat.id),
        "tenant_id": str(cat.tenant_id),
        "name": cat.name,
        "tax_type": cat.tax_type,
        "tax_rate": float(cat.tax_rate),
        "parent_id": str(cat.parent_id) if cat.parent_id else None,
        "is_active": cat.is_active,
    }


def _product_to_dict(product: Product) -> dict:
    return {
        "id": str(product.id),
        "tenant_id": str(product.tenant_id),
        "name": product.name,
        "sku": product.sku,
        "qr_code": product.qr_code,
        "barcode": product.barcode,
        "description": product.description,
        "unit": product.unit,
        "sale_price": float(product.sale_price),
        "purchase_price": float(product.purchase_price),
        "cost_average": float(product.cost_average),
        "tax_type": product.tax_type,
        "tax_rate": float(product.tax_rate),
        "stock_current": float(product.stock_current),
        "stock_minimum": float(product.stock_minimum),
        "is_low_stock": product.is_low_stock,
        "category_id": str(product.category_id) if product.category_id else None,
        "is_active": product.is_active,
    }


def _stock_level_to_dict(product: Product) -> dict:
    return {
        "product_id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "stock_current": float(product.stock_current),
        "stock_minimum": float(product.stock_minimum),
        "is_low_stock": product.is_low_stock,
        "unit": product.unit,
    }


def _movement_to_dict(m: StockMovement) -> dict:
    return {
        "id": str(m.id),
        "product_id": str(m.product_id),
        "movement_type": m.movement_type,
        "quantity": float(m.quantity),
        "stock_before": float(m.stock_before),
        "stock_after": float(m.stock_after),
        "unit_cost": float(m.unit_cost),
        "reference_type": m.reference_type,
        "reference_id": str(m.reference_id) if m.reference_id else None,
        "reason": m.reason,
        "created_at": m.created_at.isoformat(),
    }
