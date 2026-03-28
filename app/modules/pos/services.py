"""POS services — Checkout, sales, cash sessions. ACID transactions."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.modules.inventory.models import Product
from app.modules.inventory.services import move_stock
from app.modules.pos.models import CashSession, Payment, Sale, SaleItem


TWO_PLACES = Decimal("0.01")


# ── Invoice Number ────────────────────────────────────────────────

def _next_invoice_number(tenant_id: str) -> str:
    """Generate next sequential invoice number for a tenant."""
    year = datetime.now(timezone.utc).year
    prefix = f"VTA-{year}-"

    last = (
        db.session.query(func.max(Sale.invoice_number))
        .filter(Sale.tenant_id == tenant_id, Sale.invoice_number.like(f"{prefix}%"))
        .scalar()
    )

    if last:
        seq = int(last.split("-")[-1]) + 1
    else:
        seq = 1

    return f"{prefix}{seq:06d}"


# ── Cash Session Services ─────────────────────────────────────────

def open_cash_session(
    tenant_id: str, user_id: str, opening_amount: float = 0,
) -> dict:
    """Open a new cash session. Only one open session per tenant allowed."""
    existing = CashSession.query.filter_by(
        tenant_id=tenant_id, status="open"
    ).first()
    if existing:
        raise ValueError("Ya hay una caja abierta. Ciérrela antes de abrir otra.")

    session = CashSession(
        tenant_id=tenant_id,
        opened_by=user_id,
        opening_amount=Decimal(str(opening_amount)),
    )
    db.session.add(session)
    db.session.commit()
    return _cash_session_to_dict(session)


def close_cash_session(
    tenant_id: str, user_id: str, closing_amount: float, notes: str = "",
) -> dict:
    """Close the current open cash session."""
    session = CashSession.query.filter_by(
        tenant_id=tenant_id, status="open"
    ).first()
    if not session:
        raise ValueError("No hay caja abierta")

    # Calculate expected = opening + cash sales
    cash_sales_total = (
        db.session.query(func.coalesce(func.sum(Payment.amount), 0))
        .join(Sale, Payment.sale_id == Sale.id)
        .filter(
            Sale.cash_session_id == session.id,
            Sale.status == "completed",
            Payment.method == "cash",
        )
        .scalar()
    )

    session.closing_amount = Decimal(str(closing_amount))
    session.expected_amount = session.opening_amount + Decimal(str(cash_sales_total))
    session.difference = session.closing_amount - session.expected_amount
    session.closed_by = user_id
    session.closed_at = datetime.now(timezone.utc)
    session.status = "closed"
    session.notes = notes

    db.session.commit()
    return _cash_session_to_dict(session)


def get_current_session(tenant_id: str) -> Optional[dict]:
    """Get the current open cash session."""
    session = CashSession.query.filter_by(
        tenant_id=tenant_id, status="open"
    ).first()
    return _cash_session_to_dict(session) if session else None


# ── Checkout (Critical ACID Transaction) ──────────────────────────

def checkout(
    tenant_id: str, cashier_id: str, items: list, payments: list,
    customer_name: str = None, customer_tax_id: str = None,
    notes: str = None, idempotency_key: str = None,
    cash_session_id: str = None,
    sale_type: str = "cash", customer_id: str = None,
    credit_days: int = 0,
) -> dict:
    """
    Process a complete sale. ACID: Sale + StockMovements or nothing.

    items: [{"product_id": str, "quantity": float, "discount_pct": float}]
    payments: [{"method": str, "amount": float, "reference": str, "received_amount": float}]
    sale_type: "cash" (default) or "credit"
    customer_id: required for credit sales
    credit_days: payment terms for credit sales
    """
    # Idempotency check
    if idempotency_key:
        existing = Sale.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return _sale_to_dict(existing)

    # Validate items
    if not items:
        raise ValueError("La venta debe tener al menos un producto")

    # Validate credit sale requirements
    is_credit = sale_type == "credit"
    if is_credit:
        if not customer_id:
            raise ValueError("Ventas a crédito requieren un cliente")
        from app.modules.customers.models import Customer
        customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
        if not customer:
            raise ValueError("Cliente no encontrado")
        # Use customer info if not provided
        customer_name = customer_name or customer.name
        customer_tax_id = customer_tax_id or customer.tax_id
        credit_days = credit_days or customer.credit_days or 30

    # Build sale within a single transaction
    sale = Sale(
        tenant_id=tenant_id,
        cashier_id=cashier_id,
        cash_session_id=cash_session_id,
        invoice_number=_next_invoice_number(tenant_id),
        customer_id=customer_id,
        customer_name=customer_name,
        customer_tax_id=customer_tax_id,
        sale_type=sale_type,
        notes=notes,
        idempotency_key=idempotency_key or uuid.uuid4(),
    )

    total_subtotal = Decimal("0")
    total_tax = Decimal("0")
    total_discount = Decimal("0")

    sale_items = []
    stock_ops = []

    for item_data in items:
        product = Product.query.filter_by(
            id=item_data["product_id"], tenant_id=tenant_id
        ).with_for_update().first()

        if not product or not product.is_active:
            raise ValueError(f"Producto no encontrado: {item_data['product_id']}")

        qty = Decimal(str(item_data["quantity"]))
        if qty <= 0:
            raise ValueError(f"Cantidad inválida para {product.name}")

        # Stock check
        if product.stock_current < qty:
            raise ValueError(
                f"Stock insuficiente para {product.name}: "
                f"disponible={float(product.stock_current)}, solicitado={float(qty)}"
            )

        discount_pct = Decimal(str(item_data.get("discount_pct", 0)))
        unit_price = product.sale_price
        unit_cost = product.cost_average

        # Calculate line totals
        line_subtotal = (unit_price * qty).quantize(TWO_PLACES)
        line_discount = (line_subtotal * discount_pct / 100).quantize(TWO_PLACES)
        taxable_base = line_subtotal - line_discount
        line_tax = (taxable_base * product.tax_rate / 100).quantize(TWO_PLACES)
        line_total = (taxable_base + line_tax).quantize(TWO_PLACES)

        sale_item = SaleItem(
            product_id=product.id,
            product_name=product.name,
            product_sku=product.sku,
            quantity=qty,
            unit_price=unit_price,
            unit_cost=unit_cost,
            tax_rate=product.tax_rate,
            discount_pct=discount_pct,
            subtotal=taxable_base,
            tax_amount=line_tax,
            total=line_total,
        )
        sale_items.append(sale_item)

        total_subtotal += taxable_base
        total_tax += line_tax
        total_discount += line_discount

        # Queue stock movement
        stock_ops.append({
            "product": product,
            "quantity": qty,
            "unit_cost": unit_cost,
        })

    sale.subtotal = total_subtotal
    sale.tax_amount = total_tax
    sale.discount_amount = total_discount
    sale.total_amount = total_subtotal + total_tax
    sale.items = sale_items

    # Credit sale: set due date and amount_due, skip payment validation
    if is_credit:
        from datetime import timedelta
        sale.credit_days = credit_days
        sale.due_date = datetime.now(timezone.utc) + timedelta(days=credit_days)
        sale.payment_status = "pending"
        sale.amount_paid = Decimal("0")
        sale.amount_due = sale.total_amount

        # Validate credit limit
        if hasattr(customer, 'credit_limit') and customer.credit_limit > 0:
            outstanding = db.session.query(
                func.coalesce(func.sum(Sale.amount_due), 0)
            ).filter(
                Sale.tenant_id == tenant_id,
                Sale.customer_id == customer_id,
                Sale.sale_type == "credit",
                Sale.payment_status.in_(["pending", "partial", "overdue"]),
            ).scalar()
            if Decimal(str(outstanding)) + sale.total_amount > customer.credit_limit:
                raise ValueError(
                    f"Límite de crédito excedido para {customer.name}: "
                    f"límite={float(customer.credit_limit)}, pendiente={float(outstanding)}, "
                    f"nueva venta={float(sale.total_amount)}"
                )

        # Credit sales don't require payment at checkout
        sale.payments = []
    else:
        # Cash sale: validate payments cover total
        sale.payment_status = "paid"
        sale.amount_paid = sale.total_amount
        sale.amount_due = Decimal("0")

        total_paid = Decimal("0")
        sale_payments = []
        for pay_data in payments:
            amount = Decimal(str(pay_data["amount"]))
            received = Decimal(str(pay_data.get("received_amount", amount)))
            change = (received - amount).quantize(TWO_PLACES) if received > amount else Decimal("0")

            payment = Payment(
                tenant_id=tenant_id,
                method=pay_data["method"],
                amount=amount,
                reference=pay_data.get("reference"),
                received_amount=received,
                change_amount=change,
            )
            sale_payments.append(payment)
            total_paid += amount

        if total_paid < sale.total_amount:
            raise ValueError(
                f"Pago insuficiente: total={float(sale.total_amount)}, "
                f"pagado={float(total_paid)}"
            )

        sale.payments = sale_payments

    # Persist sale
    db.session.add(sale)
    db.session.flush()

    # Execute stock movements (same transaction)
    for op in stock_ops:
        product = op["product"]
        qty = op["quantity"]
        stock_before = product.stock_current
        product.stock_current -= qty

        from app.modules.inventory.models import StockMovement
        movement = StockMovement(
            tenant_id=tenant_id,
            product_id=product.id,
            created_by=cashier_id,
            movement_type="sale",
            quantity=qty,
            stock_before=stock_before,
            stock_after=product.stock_current,
            unit_cost=op["unit_cost"],
            reference_type="sale",
            reference_id=sale.id,
        )
        db.session.add(movement)

    # Auto-post accounting entries (same transaction)
    cost_total = sum(
        float(op["unit_cost"]) * float(op["quantity"]) for op in stock_ops
    )
    payment_method = payments[0]["method"] if payments else "cash"

    try:
        from app.modules.accounting.services import post_sale_entry
        from app.modules.auth_rbac.models import Tenant
        tenant_obj = Tenant.query.get(tenant_id)
        fiscal = tenant_obj.fiscal_regime if tenant_obj else "simplified"
        post_sale_entry(
            tenant_id=tenant_id, created_by=cashier_id,
            sale_id=str(sale.id),
            subtotal=float(sale.subtotal), tax_amount=float(sale.tax_amount),
            total_amount=float(sale.total_amount), cost_total=cost_total,
            payment_method="credit" if is_credit else payment_method,
            fiscal_regime=fiscal,
        )
    except Exception:
        pass  # Accounting failure should not block the sale

    # Commit everything atomically
    db.session.commit()
    return _sale_to_dict(sale)


# ── Sale Queries ──────────────────────────────────────────────────

def get_sale(tenant_id: str, sale_id: str) -> Optional[dict]:
    """Get a sale by ID."""
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tenant_id).first()
    return _sale_to_dict(sale) if sale else None


def get_sale_by_invoice(tenant_id: str, invoice_number: str) -> Optional[dict]:
    """Get a sale by invoice number."""
    sale = Sale.query.filter_by(
        tenant_id=tenant_id, invoice_number=invoice_number
    ).first()
    return _sale_to_dict(sale) if sale else None


def list_sales(
    tenant_id: str, page: int = 1, per_page: int = 20,
    status: str = None, cashier_id: str = None,
    date_from: str = None, date_to: str = None,
) -> dict:
    """List sales with filters."""
    from sqlalchemy.orm import joinedload
    q = Sale.query.filter_by(tenant_id=tenant_id)

    if status:
        q = q.filter(Sale.status == status)
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    if date_from:
        q = q.filter(Sale.sale_date >= date_from)
    if date_to:
        q = q.filter(Sale.sale_date <= date_to)

    total = q.count()
    # Eager load items + payments to avoid N+1 queries (42→3 queries per page)
    sales = q.options(
        joinedload(Sale.items),
        joinedload(Sale.payments),
    ).order_by(Sale.sale_date.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return {
        "data": [_sale_summary_to_dict(s) for s in sales],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "has_next": page * per_page < total,
        },
    }


def get_daily_totals(tenant_id: str, date: str = None) -> dict:
    """Get sales summary for a specific date."""
    from zoneinfo import ZoneInfo
    if not date:
        date = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d")

    result = (
        db.session.query(
            func.count(Sale.id).label("total_sales"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total_revenue"),
            func.coalesce(func.sum(Sale.tax_amount), 0).label("total_tax"),
            func.coalesce(func.avg(Sale.total_amount), 0).label("avg_ticket"),
        )
        .filter(
            Sale.tenant_id == tenant_id,
            Sale.status == "completed",
            func.date(func.timezone("America/Bogota", Sale.sale_date)) == date,
        )
        .first()
    )

    return {
        "date": date,
        "total_sales": result.total_sales or 0,
        "total_revenue": float(result.total_revenue or 0),
        "total_tax": float(result.total_tax or 0),
        "avg_ticket": float(result.avg_ticket or 0),
    }


# ── Void Sale ─────────────────────────────────────────────────────

def void_sale(
    tenant_id: str, sale_id: str, user_id: str, reason: str,
) -> dict:
    """Void a completed sale. Restores stock."""
    sale = Sale.query.filter_by(
        id=sale_id, tenant_id=tenant_id, status="completed"
    ).first()
    if not sale:
        raise ValueError("Venta no encontrada o ya anulada")

    # Mark as voided
    sale.status = "voided"
    sale.voided_at = datetime.now(timezone.utc)
    sale.voided_by = user_id
    sale.void_reason = reason

    # Restore stock for each item
    for item in sale.items:
        product = Product.query.filter_by(
            id=item.product_id, tenant_id=tenant_id
        ).with_for_update().first()

        if product:
            stock_before = product.stock_current
            product.stock_current += item.quantity

            from app.modules.inventory.models import StockMovement
            movement = StockMovement(
                tenant_id=tenant_id,
                product_id=product.id,
                created_by=user_id,
                movement_type="return_sale",
                quantity=item.quantity,
                stock_before=stock_before,
                stock_after=product.stock_current,
                unit_cost=item.unit_cost,
                reference_type="sale_void",
                reference_id=sale.id,
                reason=f"Anulación: {reason}",
            )
            db.session.add(movement)

    # Auto-post reversal accounting entries
    cost_total = sum(float(item.unit_cost) * float(item.quantity) for item in sale.items)
    payment_method = sale.payments[0].method if sale.payments else "cash"
    try:
        from app.modules.accounting.services import post_sale_reversal
        post_sale_reversal(
            tenant_id=tenant_id, created_by=user_id,
            sale_id=str(sale.id),
            subtotal=float(sale.subtotal), tax_amount=float(sale.tax_amount),
            total_amount=float(sale.total_amount), cost_total=cost_total,
            payment_method=payment_method,
        )
    except Exception:
        pass

    db.session.commit()
    return _sale_to_dict(sale)


# ── Partial Return / Credit Note ──────────────────────────────────

def create_return(
    tenant_id: str, sale_id: str, user_id: str,
    items: list, reason: str,
) -> dict:
    """
    Create a partial return (credit note).
    items: [{"product_id": str, "quantity": float}]
    """
    from app.modules.pos.models import CreditNote, CreditNoteItem

    sale = Sale.query.filter_by(id=sale_id, tenant_id=tenant_id, status="completed").first()
    if not sale:
        raise ValueError("Venta no encontrada o no está completada")

    # Generate credit note number
    year = datetime.now(timezone.utc).year
    prefix = f"NC-{year}-"
    last = (
        db.session.query(func.max(CreditNote.credit_note_number))
        .filter(CreditNote.tenant_id == tenant_id, CreditNote.credit_note_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    cn_number = f"{prefix}{seq:06d}"

    cn = CreditNote(
        tenant_id=tenant_id, sale_id=sale.id, created_by=user_id,
        credit_note_number=cn_number, reason=reason,
    )

    total_sub = Decimal("0")
    total_tax = Decimal("0")
    total_cost = Decimal("0")

    for ret_item in items:
        # Find original sale item
        sale_item = next(
            (si for si in sale.items if str(si.product_id) == ret_item["product_id"]),
            None
        )
        if not sale_item:
            raise ValueError(f"Producto {ret_item['product_id']} no está en esta venta")

        qty = Decimal(str(ret_item["quantity"]))
        if qty <= 0 or qty > sale_item.quantity:
            raise ValueError(f"Cantidad inválida para {sale_item.product_name}: máx {sale_item.quantity}")

        line_sub = (sale_item.unit_price * qty).quantize(Decimal("0.01"))
        line_tax = (line_sub * sale_item.tax_rate / 100).quantize(Decimal("0.01"))
        line_cost = (sale_item.unit_cost * qty).quantize(Decimal("0.01"))

        cn_item = CreditNoteItem(
            product_id=sale_item.product_id, product_name=sale_item.product_name,
            quantity=qty, unit_price=sale_item.unit_price, unit_cost=sale_item.unit_cost,
            tax_rate=sale_item.tax_rate, subtotal=line_sub, tax_amount=line_tax,
            total=line_sub + line_tax,
        )
        cn.items.append(cn_item)
        total_sub += line_sub
        total_tax += line_tax
        total_cost += line_cost

        # Restore stock
        product = Product.query.filter_by(
            id=sale_item.product_id, tenant_id=tenant_id
        ).with_for_update().first()
        if product:
            stock_before = product.stock_current
            product.stock_current += qty
            from app.modules.inventory.models import StockMovement
            db.session.add(StockMovement(
                tenant_id=tenant_id, product_id=product.id, created_by=user_id,
                movement_type="return_sale", quantity=qty,
                stock_before=stock_before, stock_after=product.stock_current,
                unit_cost=sale_item.unit_cost,
                reference_type="credit_note", reference_id=cn.id,
                reason=f"Devolución: {reason}",
            ))

    cn.subtotal = total_sub
    cn.tax_amount = total_tax
    cn.total_amount = total_sub + total_tax

    db.session.add(cn)
    db.session.flush()

    # Auto-post credit note accounting (uses PUC 4175 Devoluciones)
    try:
        from app.modules.accounting.services import post_sale_credit_note_entry
        payment_method = sale.payments[0].method if sale.payments else "cash"
        post_sale_credit_note_entry(
            tenant_id=tenant_id, created_by=user_id,
            sale_id=str(sale.id), credit_note_id=str(cn.id),
            subtotal=float(total_sub), tax_amount=float(total_tax),
            total_amount=float(cn.total_amount), cost_total=float(total_cost),
            payment_method=payment_method,
        )
    except Exception:
        pass

    db.session.commit()

    return {
        "credit_note_number": cn.credit_note_number,
        "sale_invoice": sale.invoice_number,
        "reason": cn.reason,
        "subtotal": float(cn.subtotal),
        "tax_amount": float(cn.tax_amount),
        "total_amount": float(cn.total_amount),
        "items": [
            {"product": i.product_name, "qty": float(i.quantity),
             "unit_price": float(i.unit_price), "total": float(i.total)}
            for i in cn.items
        ],
    }


# ── Overdue Auto-marking ─────────────────────────────────────────

def mark_overdue_sales(tenant_id: str) -> int:
    """Mark credit sales as overdue when due_date has passed."""
    now = datetime.now(timezone.utc)
    count = Sale.query.filter(
        Sale.tenant_id == tenant_id,
        Sale.sale_type == "credit",
        Sale.payment_status == "pending",
        Sale.due_date < now,
    ).update({"payment_status": "overdue"})
    if count > 0:
        db.session.commit()
    return count


# ── Serializers ───────────────────────────────────────────────────

def _cash_session_to_dict(session: CashSession) -> dict:
    return {
        "id": str(session.id),
        "tenant_id": str(session.tenant_id),
        "status": session.status,
        "opening_amount": float(session.opening_amount),
        "closing_amount": float(session.closing_amount) if session.closing_amount else None,
        "expected_amount": float(session.expected_amount) if session.expected_amount else None,
        "difference": float(session.difference) if session.difference else None,
        "opened_at": session.opened_at.isoformat(),
        "closed_at": session.closed_at.isoformat() if session.closed_at else None,
        "notes": session.notes,
    }


def _sale_to_dict(sale: Sale) -> dict:
    return {
        "id": str(sale.id),
        "tenant_id": str(sale.tenant_id),
        "invoice_number": sale.invoice_number,
        "sale_date": sale.sale_date.isoformat(),
        "status": sale.status,
        # Amounts
        "subtotal": float(sale.subtotal),
        "tax_amount": float(sale.tax_amount),
        "discount_amount": float(sale.discount_amount),
        "total_amount": float(sale.total_amount),
        # Credit / payment tracking fields
        "sale_type": sale.sale_type,
        "payment_status": sale.payment_status,
        "amount_paid": float(sale.amount_paid),
        "amount_due": float(sale.amount_due),
        "credit_days": sale.credit_days,
        "due_date": sale.due_date.isoformat() if sale.due_date else None,
        # Customer
        "customer_id": str(sale.customer_id) if sale.customer_id else None,
        "customer_name": sale.customer_name,
        "customer_tax_id": sale.customer_tax_id,
        # Relations
        "items": [_sale_item_to_dict(i) for i in sale.items],
        "payments": [_payment_to_dict(p) for p in sale.payments],
        # Void
        "voided_at": sale.voided_at.isoformat() if sale.voided_at else None,
        "void_reason": sale.void_reason,
    }


def _sale_summary_to_dict(sale: Sale) -> dict:
    return {
        "id": str(sale.id),
        "invoice_number": sale.invoice_number,
        "sale_date": sale.sale_date.isoformat(),
        "status": sale.status,
        "total_amount": float(sale.total_amount),
        "items_count": len(sale.items),
        "payment_method": sale.payments[0].method if sale.payments else None,
    }


def _sale_item_to_dict(item: SaleItem) -> dict:
    return {
        "product_id": str(item.product_id),
        "product_name": item.product_name,
        "quantity": float(item.quantity),
        "unit_price": float(item.unit_price),
        "unit_cost": float(item.unit_cost),
        "tax_rate": float(item.tax_rate),
        "discount_pct": float(item.discount_pct),
        "subtotal": float(item.subtotal),
        "tax_amount": float(item.tax_amount),
        "total": float(item.total),
    }


def _payment_to_dict(payment: Payment) -> dict:
    return {
        "method": payment.method,
        "amount": float(payment.amount),
        "received_amount": float(payment.received_amount) if payment.received_amount else None,
        "change_amount": float(payment.change_amount) if payment.change_amount else None,
        "reference": payment.reference,
    }
