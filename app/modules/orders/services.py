"""Order services — create, confirm, update state, close, cancel. No accounting until close."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.modules.inventory.models import Product
from app.modules.orders.constants import (
    ORDER_NUMBER_PREFIX,
    TRANSITION_MAP,
    OrderStatus,
)
from app.modules.orders.exceptions import (
    CloseOrderStockError,
    OrderMaxOpenError,
    OrderNotFoundError,
    OrderStateError,
)
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory

TWO_PLACES = Decimal("0.01")


# ── Order Number ─────────────────────────────────────────────────


def _next_order_number(tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    prefix = f"{ORDER_NUMBER_PREFIX}-{now.year}{now.month:02d}-"
    last = (
        db.session.query(func.max(Order.order_number))
        .filter(Order.tenant_id == tenant_id, Order.order_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


# ── Create Order ─────────────────────────────────────────────────


def create_order(
    tenant_id: str,
    created_by: str,
    items: list,
    vertical_type: str = "restaurant",
    table_number: str = None,
    customer_name: str = None,
    customer_phone: str = None,
    delivery_address: str = None,
    notes: str = None,
    assigned_to: str = None,
    branch_id: str = None,
    is_wholesale: bool = False,
) -> dict:
    """
    Create a new order in DRAFT status.
    Does NOT validate stock. Does NOT touch accounting.
    items: [{"product_id": str, "quantity": float, "notes": str}]
    """
    # Check max open orders
    from app.modules.auth_rbac.models import Tenant

    tenant = Tenant.query.get(tenant_id)
    if tenant and tenant.orders_config:
        max_open = tenant.orders_config.get("max_open_orders", 50)
        active_count = Order.query.filter(
            Order.tenant_id == tenant_id, Order.status.in_(list(OrderStatus.ACTIVE))
        ).count()
        if active_count >= max_open:
            raise OrderMaxOpenError(f"Limite de {max_open} pedidos abiertos alcanzado")

    if not items:
        raise ValueError("El pedido debe tener al menos un item")

    order = Order(
        tenant_id=tenant_id,
        order_number=_next_order_number(tenant_id),
        status=OrderStatus.DRAFT,
        vertical_type=vertical_type,
        table_number=table_number,
        customer_name=customer_name,
        customer_phone=customer_phone,
        delivery_address=delivery_address,
        notes=notes,
        created_by=created_by,
        assigned_to=assigned_to,
        branch_id=branch_id,
        is_wholesale=is_wholesale,
    )

    total_preview = Decimal("0")
    order_items = []

    for item_data in items:
        product = Product.query.filter_by(id=item_data["product_id"], tenant_id=tenant_id).first()
        if not product or not product.is_active:
            raise ValueError(f"Producto no encontrado: {item_data['product_id']}")

        qty = Decimal(str(item_data["quantity"]))
        if qty <= 0:
            raise ValueError(f"Cantidad invalida para {product.name}")

        from app.modules.inventory.services import resolve_item_price

        unit_price, price_tier = resolve_item_price(product, is_wholesale)
        subtotal = (unit_price * qty).quantize(TWO_PLACES)

        oi = OrderItem(
            tenant_id=tenant_id,
            product_id=product.id,
            product_name=product.name,
            product_sku=product.sku,
            unit_price=unit_price,
            quantity=qty,
            subtotal=subtotal,
            price_tier=price_tier,
            notes=item_data.get("notes"),
        )
        order_items.append(oi)
        total_preview += subtotal

    order.total_preview = total_preview
    order.items = order_items

    db.session.add(order)

    # Log initial state
    _log_status_change(order, None, OrderStatus.DRAFT, created_by)

    db.session.commit()
    return _order_to_dict(order)


# ── Confirm Order ────────────────────────────────────────────────


def confirm_order(order_id: str, tenant_id: str, confirmed_by: str) -> dict:
    """
    Transition DRAFT → CONFIRMED.
    Performs soft stock check (no lock, no decrement).
    """
    order = _get_order_or_404(order_id, tenant_id)
    _validate_transition(order, OrderStatus.CONFIRMED)

    # Soft stock check — advisory, not a reservation
    for item in order.items:
        product = Product.query.filter_by(id=item.product_id, tenant_id=tenant_id).first()
        if product and product.stock_current < item.quantity:
            raise ValueError(
                f"Stock insuficiente para {item.product_name}: "
                f"disponible={float(product.stock_current)}, pedido={float(item.quantity)}"
            )

    old_status = order.status
    order.status = OrderStatus.CONFIRMED
    _log_status_change(order, old_status, OrderStatus.CONFIRMED, confirmed_by)
    db.session.commit()
    return _order_to_dict(order)


# ── Update Order State (generic) ─────────────────────────────────


def update_order_state(order_id: str, tenant_id: str, new_status: str, changed_by: str, reason: str = None) -> dict:
    """Generic state transition. Validates against TRANSITION_MAP."""
    order = _get_order_or_404(order_id, tenant_id)
    _validate_transition(order, new_status)

    old_status = order.status
    order.status = new_status
    _log_status_change(order, old_status, new_status, changed_by, reason)
    db.session.commit()
    return _order_to_dict(order)


# ── Add Items to Order ───────────────────────────────────────────


def add_items_to_order(order_id: str, tenant_id: str, items: list, added_by: str) -> dict:
    """Add items to an existing order. Marks as added_after_confirmation if not in DRAFT."""
    order = _get_order_or_404(order_id, tenant_id)

    if order.status in OrderStatus.TERMINAL:
        raise OrderStateError("No se pueden agregar items a un pedido cerrado o cancelado")

    after_confirm = order.status != OrderStatus.DRAFT

    for item_data in items:
        product = Product.query.filter_by(id=item_data["product_id"], tenant_id=tenant_id).first()
        if not product or not product.is_active:
            raise ValueError(f"Producto no encontrado: {item_data['product_id']}")

        qty = Decimal(str(item_data["quantity"]))

        from app.modules.inventory.services import resolve_item_price

        unit_price, price_tier = resolve_item_price(product, order.is_wholesale)
        subtotal = (unit_price * qty).quantize(TWO_PLACES)

        oi = OrderItem(
            order_id=order.id,
            tenant_id=tenant_id,
            product_id=product.id,
            product_name=product.name,
            product_sku=product.sku,
            unit_price=unit_price,
            quantity=qty,
            subtotal=subtotal,
            price_tier=price_tier,
            notes=item_data.get("notes"),
            added_after_confirmation=after_confirm,
        )
        db.session.add(oi)
        order.total_preview += subtotal

    db.session.commit()
    return _order_to_dict(order)


# ── Close Order → Create Sale ────────────────────────────────────


def close_order(
    order_id: str,
    tenant_id: str,
    closed_by: str,
    payment_method: str,
    idempotency_key: str,
    received_amount: float = None,
    reference: str = None,
    voucher_code: str = None,
    voucher_amount: float = None,
) -> dict:
    """
    ACID: Close order → create Sale + Stock + Accounting.
    Uses SELECT FOR UPDATE on order row for idempotency.
    """
    try:
        order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).with_for_update(nowait=True).first()
    except OperationalError:
        raise OrderStateError("El pedido esta siendo procesado por otro usuario")

    if not order:
        raise OrderNotFoundError()

    # Idempotency guard
    if order.status == OrderStatus.CLOSED:
        return {"order_id": str(order.id), "sale_id": str(order.sale_id), "already_closed": True}

    if not order.is_closable:
        raise OrderStateError(f"El pedido en estado '{order.status}' no se puede cerrar. Debe estar en 'listo'.")

    # Build items for create_sale_from_items
    sale_items = [
        {"product_id": str(item.product_id), "quantity": float(item.quantity), "discount_pct": 0}
        for item in order.items
    ]

    # Build payments
    total = float(order.total_preview)
    payments = []

    voucher_redemption = None
    if voucher_code and voucher_amount:
        voucher_redemption = {
            "code": voucher_code,
            "amount": voucher_amount,
            "idempotency_key": str(uuid.uuid4()),
        }
        cash_portion = total - voucher_amount
        payments.append({"method": "voucher", "amount": voucher_amount})
        if cash_portion > 0:
            payments.append(
                {
                    "method": payment_method,
                    "amount": cash_portion,
                    "received_amount": received_amount or cash_portion,
                    "reference": reference,
                }
            )
    else:
        payments.append(
            {
                "method": payment_method,
                "amount": total,
                "received_amount": received_amount or total,
                "reference": reference,
            }
        )

    # Create sale via shared POS logic (NO commit — we do it after updating order)
    try:
        from app.modules.pos.services import create_sale_from_items

        sale_result = create_sale_from_items(
            tenant_id=tenant_id,
            created_by=closed_by,
            items=sale_items,
            payments=payments,
            sale_type="cash",
            idempotency_key=idempotency_key,
            voucher_redemption=voucher_redemption,
            source_order_id=str(order.id),
            auto_commit=False,
            is_wholesale=order.is_wholesale,
        )
    except ValueError as e:
        # Stock insufficient or other validation error
        order.status = OrderStatus.CLOSE_FAILED
        _log_status_change(order, OrderStatus.READY, OrderStatus.CLOSE_FAILED, closed_by, str(e))
        db.session.commit()
        raise CloseOrderStockError(str(e))

    # Update order to CLOSED
    order.status = OrderStatus.CLOSED
    order.sale_id = sale_result["id"]
    order.closed_by = closed_by
    order.closed_at = datetime.now(timezone.utc)
    order.idempotency_key = idempotency_key

    _log_status_change(order, OrderStatus.READY, OrderStatus.CLOSED, closed_by)

    # Single atomic commit: Sale + Stock + Accounting + Order status
    db.session.commit()

    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "sale_id": sale_result["id"],
        "total_charged": sale_result["total_amount"],
        "already_closed": False,
        "sale": sale_result,
    }


# ── Cancel Order ─────────────────────────────────────────────────


def cancel_order(order_id: str, tenant_id: str, cancelled_by: str, reason: str) -> dict:
    """Cancel an order. Allowed from any state before CLOSED. Does NOT touch accounting."""
    order = _get_order_or_404(order_id, tenant_id)

    if order.status in OrderStatus.TERMINAL:
        raise OrderStateError("No se puede cancelar un pedido que ya esta cerrado o cancelado")

    if not reason:
        raise ValueError("Debe indicar la razon de cancelacion")

    old_status = order.status
    order.status = OrderStatus.CANCELLED
    order.cancelled_by = cancelled_by
    order.cancelled_at = datetime.now(timezone.utc)
    order.cancel_reason = reason

    _log_status_change(order, old_status, OrderStatus.CANCELLED, cancelled_by, reason)
    db.session.commit()
    return _order_to_dict(order)


# ── Queries ──────────────────────────────────────────────────────


def get_order(tenant_id: str, order_id: str) -> Optional[dict]:
    order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    return _order_to_dict(order) if order else None


def list_orders(
    tenant_id: str, page: int = 1, per_page: int = 20, status: str = None, table_number: str = None
) -> dict:
    q = Order.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter(Order.status == status)
    if table_number:
        q = q.filter(Order.table_number == table_number)

    total = q.count()
    from sqlalchemy.orm import joinedload

    orders = (
        q.options(joinedload(Order.items))
        .order_by(Order.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "data": [_order_to_dict(o) for o in orders],
        "pagination": {"page": page, "per_page": per_page, "total": total, "has_next": page * per_page < total},
    }


def get_kds_orders(tenant_id: str, branch_id: str = None) -> list:
    """Get active orders for KDS (kitchen display). Sorted by creation time (oldest first)."""
    q = Order.query.filter(Order.tenant_id == tenant_id, Order.status.in_(list(OrderStatus.KDS_VISIBLE)))
    if branch_id:
        q = q.filter(Order.branch_id == branch_id)

    from sqlalchemy.orm import joinedload

    orders = q.options(joinedload(Order.items)).order_by(Order.created_at.asc()).all()
    return [_order_to_dict(o) for o in orders]


def get_order_stats(tenant_id: str) -> dict:
    stats = (
        db.session.query(Order.status, func.count(Order.id).label("count"))
        .filter(Order.tenant_id == tenant_id)
        .group_by(Order.status)
        .all()
    )
    result = {"by_status": {}, "active_count": 0, "total_today": 0}
    for row in stats:
        result["by_status"][row.status] = row.count
        if row.status in OrderStatus.ACTIVE:
            result["active_count"] += row.count

    # Today's orders
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d")
    result["total_today"] = Order.query.filter(
        Order.tenant_id == tenant_id,
        func.date(func.timezone("America/Bogota", Order.created_at)) == today,
    ).count()
    return result


def get_order_history(tenant_id: str, order_id: str) -> list:
    history = (
        OrderStatusHistory.query.filter_by(order_id=order_id, tenant_id=tenant_id)
        .order_by(OrderStatusHistory.changed_at.desc())
        .all()
    )
    return [
        {
            "from_status": h.from_status,
            "to_status": h.to_status,
            "changed_by": str(h.changed_by),
            "reason": h.reason,
            "changed_at": h.changed_at.isoformat(),
        }
        for h in history
    ]


# ── Internal Helpers ─────────────────────────────────────────────


def _get_order_or_404(order_id: str, tenant_id: str) -> Order:
    order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order:
        raise OrderNotFoundError()
    return order


def _validate_transition(order: Order, new_status: str):
    allowed = TRANSITION_MAP.get(order.status, [])
    if new_status not in allowed:
        raise OrderStateError(
            f"Transicion de '{order.status}' a '{new_status}' no permitida. "
            f"Estados permitidos: {', '.join(allowed) if allowed else 'ninguno (estado terminal)'}"
        )


def _log_status_change(order: Order, from_status: str, to_status: str, changed_by: str, reason: str = None):
    entry = OrderStatusHistory(
        order_id=order.id,
        tenant_id=order.tenant_id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        reason=reason,
    )
    db.session.add(entry)


# ── Serializers ──────────────────────────────────────────────────

STATUS_LABELS = {
    "draft": "Borrador",
    "confirmed": "Confirmado",
    "in_preparation": "En preparacion",
    "ready": "Listo",
    "closed": "Cerrado",
    "cancelled": "Cancelado",
    "close_failed": "Error al cerrar",
}


def _order_to_dict(order: Order) -> dict:
    return {
        "id": str(order.id),
        "tenant_id": str(order.tenant_id),
        "order_number": order.order_number,
        "status": order.status,
        "status_label": STATUS_LABELS.get(order.status, order.status),
        "is_wholesale": order.is_wholesale,
        "vertical_type": order.vertical_type,
        "table_number": order.table_number,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "delivery_address": order.delivery_address,
        "notes": order.notes,
        "total_preview": float(order.total_preview),
        "sale_id": str(order.sale_id) if order.sale_id else None,
        "assigned_to": str(order.assigned_to) if order.assigned_to else None,
        "created_by": str(order.created_by),
        "created_at": order.created_at.isoformat(),
        "closed_at": order.closed_at.isoformat() if order.closed_at else None,
        "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
        "cancel_reason": order.cancel_reason,
        "is_active": order.is_active,
        "is_closable": order.is_closable,
        "items": [_order_item_to_dict(i) for i in order.items],
        "items_count": len(order.items),
    }


def _order_item_to_dict(item: OrderItem) -> dict:
    return {
        "id": str(item.id),
        "product_id": str(item.product_id),
        "product_name": item.product_name,
        "product_sku": item.product_sku,
        "unit_price": float(item.unit_price),
        "quantity": float(item.quantity),
        "subtotal": float(item.subtotal),
        "price_tier": item.price_tier,
        "notes": item.notes,
        "added_after_confirmation": item.added_after_confirmation,
        "added_at": item.added_at.isoformat(),
    }
