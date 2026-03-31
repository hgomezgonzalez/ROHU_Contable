"""Purchases services — Suppliers, POs, receiving with stock + accounting."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.modules.inventory.models import Product, StockMovement
from app.modules.purchases.models import (
    PurchaseOrder, PurchaseOrderItem, Supplier,
    SupplierPayment, PurchaseCreditNote, PurchaseCreditNoteItem, PurchaseDebitNote,
)


TWO_PLACES = Decimal("0.01")


# ── PO Number ─────────────────────────────────────────────────────

def _next_po_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"OC-{year}-"
    last = (
        db.session.query(func.max(PurchaseOrder.order_number))
        .filter(PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.order_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


# ── Supplier Services ─────────────────────────────────────────────

def create_supplier(
    tenant_id: str, created_by: str, name: str,
    tax_id: str = None, contact_name: str = None,
    phone: str = None, email: str = None, address: str = None,
    city: str = None, payment_terms_days: int = 0,
) -> dict:
    supplier = Supplier(
        tenant_id=tenant_id, created_by=created_by, name=name,
        tax_id=tax_id, contact_name=contact_name, phone=phone,
        email=email, address=address, city=city,
        payment_terms_days=payment_terms_days,
    )
    db.session.add(supplier)
    db.session.commit()
    return _supplier_to_dict(supplier)


def get_suppliers(tenant_id: str) -> list:
    suppliers = Supplier.query.filter(
        Supplier.tenant_id == tenant_id,
        Supplier.is_active.is_(True),
        Supplier.deleted_at.is_(None),
    ).order_by(Supplier.name).all()
    return [_supplier_to_dict(s) for s in suppliers]


def update_supplier(tenant_id: str, supplier_id: str, **kwargs) -> dict:
    """Update supplier info."""
    supplier = Supplier.query.filter_by(id=supplier_id, tenant_id=tenant_id).first()
    if not supplier:
        raise ValueError("Proveedor no encontrado")
    allowed = {"name", "tax_id", "contact_name", "phone", "email", "address", "city", "payment_terms_days"}
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            setattr(supplier, k, v)
    db.session.commit()
    return _supplier_to_dict(supplier)


# ── Purchase Order Services ───────────────────────────────────────

def create_purchase_order(
    tenant_id: str, created_by: str, supplier_id: str,
    items: list, payment_type: str = "cash",
    expected_date: str = None, supplier_invoice: str = None,
    notes: str = None,
) -> dict:
    """
    Create a purchase order.
    items: [{"product_id": str, "quantity": float, "unit_cost": float, "tax_rate": float}]
    """
    supplier = Supplier.query.filter_by(
        id=supplier_id, tenant_id=tenant_id
    ).first()
    if not supplier:
        raise ValueError("Proveedor no encontrado")

    po = PurchaseOrder(
        tenant_id=tenant_id, supplier_id=supplier_id, created_by=created_by,
        order_number=_next_po_number(tenant_id),
        payment_type=payment_type,
        supplier_invoice=supplier_invoice,
        notes=notes,
    )
    if expected_date:
        po.expected_date = expected_date

    total_sub = Decimal("0")
    total_tax = Decimal("0")

    for item_data in items:
        if item_data.get("product_id"):
            # Existing product
            product = Product.query.filter_by(
                id=item_data["product_id"], tenant_id=tenant_id
            ).first()
            if not product:
                raise ValueError(f"Producto no encontrado: {item_data['product_id']}")
        elif item_data.get("product_name"):
            # New product — create draft
            from app.modules.inventory.services import create_product_draft
            product = create_product_draft(
                tenant_id=tenant_id, created_by=created_by,
                name=item_data["product_name"],
                purchase_price=float(item_data.get("unit_cost", 0)),
                tax_type=item_data.get("tax_type", "iva_19"),
            )
        else:
            raise ValueError("Cada item requiere product_id o product_name")

        qty = Decimal(str(item_data["quantity"]))
        cost = Decimal(str(item_data["unit_cost"]))
        rate = Decimal(str(item_data.get("tax_rate", 19.0)))

        line_sub = (qty * cost).quantize(TWO_PLACES)
        line_tax = (line_sub * rate / 100).quantize(TWO_PLACES)
        line_total = line_sub + line_tax

        po_item = PurchaseOrderItem(
            product_id=product.id, product_name=product.name,
            quantity_ordered=qty, unit_cost=cost, tax_rate=rate,
            subtotal=line_sub, tax_amount=line_tax, total=line_total,
        )
        po.items.append(po_item)
        total_sub += line_sub
        total_tax += line_tax

    po.subtotal = total_sub
    po.tax_amount = total_tax
    po.total_amount = total_sub + total_tax

    db.session.add(po)
    db.session.commit()
    return _po_to_dict(po)


def update_purchase_order(tenant_id: str, po_id: str, **kwargs) -> dict:
    """Update a draft PO. Only draft OCs can be edited."""
    po = _get_po(tenant_id, po_id)
    if po.status != "draft":
        raise ValueError(f"Solo se puede editar una OC en estado borrador (actual: {po.status})")

    # Update simple fields
    for field in ("payment_type", "supplier_invoice", "notes", "expected_date"):
        if field in kwargs and kwargs[field] is not None:
            setattr(po, field, kwargs[field])

    # Update items if provided
    new_items = kwargs.get("items")
    if new_items is not None:
        # Remove old items
        for item in po.items:
            db.session.delete(item)
        db.session.flush()

        # Add new items
        total_sub = Decimal("0")
        total_tax = Decimal("0")
        for item_data in new_items:
            product = Product.query.filter_by(id=item_data["product_id"], tenant_id=tenant_id).first()
            if not product:
                raise ValueError(f"Producto no encontrado: {item_data['product_id']}")
            qty = Decimal(str(item_data["quantity"]))
            cost = Decimal(str(item_data["unit_cost"]))
            rate = Decimal(str(item_data.get("tax_rate", 19.0)))
            line_sub = (qty * cost).quantize(TWO_PLACES)
            line_tax = (line_sub * rate / 100).quantize(TWO_PLACES)
            po.items.append(PurchaseOrderItem(
                product_id=product.id, product_name=product.name,
                quantity_ordered=qty, unit_cost=cost, tax_rate=rate,
                subtotal=line_sub, tax_amount=line_tax, total=line_sub + line_tax,
            ))
            total_sub += line_sub
            total_tax += line_tax
        po.subtotal = total_sub
        po.tax_amount = total_tax
        po.total_amount = total_sub + total_tax

    db.session.commit()
    return _po_to_dict(po)


def send_purchase_order(tenant_id: str, po_id: str) -> dict:
    """Mark a PO as sent to supplier."""
    po = _get_po(tenant_id, po_id)
    if po.status != "draft":
        raise ValueError(f"Solo se puede enviar una OC en estado draft, actual: {po.status}")
    po.status = "sent"
    db.session.commit()
    return _po_to_dict(po)


def receive_purchase_order(
    tenant_id: str, po_id: str, user_id: str,
    received_items: list = None,
) -> dict:
    """
    Receive a PO: update stock + generate accounting entry.
    received_items: [{"item_id": str, "quantity_received": float}]
    If None, receive all items in full.
    """
    po = _get_po(tenant_id, po_id)
    if po.status not in ("sent", "partially_received"):
        raise ValueError(f"No se puede recibir una OC en estado: {po.status}")

    all_complete = True
    total_cost = Decimal("0")
    total_tax = Decimal("0")

    for po_item in po.items:
        qty_to_receive = None

        if received_items:
            match = next(
                (r for r in received_items if r.get("item_id") == str(po_item.id)),
                None
            )
            if match:
                qty_to_receive = Decimal(str(match["quantity_received"]))
        else:
            qty_to_receive = po_item.quantity_ordered - po_item.quantity_received

        if qty_to_receive is None or qty_to_receive <= 0:
            if po_item.quantity_received < po_item.quantity_ordered:
                all_complete = False
            continue

        # Update PO item
        po_item.quantity_received += qty_to_receive

        if po_item.quantity_received < po_item.quantity_ordered:
            all_complete = False

        # Update product stock
        product = Product.query.filter_by(
            id=po_item.product_id, tenant_id=tenant_id
        ).with_for_update().first()

        if product:
            stock_before = product.stock_current
            product.stock_current += qty_to_receive

            # Update cost average
            if product.stock_current > 0:
                total_value = (stock_before * product.cost_average) + (qty_to_receive * po_item.unit_cost)
                product.cost_average = total_value / product.stock_current

            # Record stock movement
            movement = StockMovement(
                tenant_id=tenant_id, product_id=product.id, created_by=user_id,
                movement_type="purchase_receipt", quantity=qty_to_receive,
                stock_before=stock_before, stock_after=product.stock_current,
                unit_cost=po_item.unit_cost,
                reference_type="purchase_order", reference_id=po.id,
            )
            db.session.add(movement)

            item_cost = (qty_to_receive * po_item.unit_cost).quantize(TWO_PLACES)
            item_tax = (item_cost * po_item.tax_rate / 100).quantize(TWO_PLACES)
            total_cost += item_cost
            total_tax += item_tax

    po.status = "received" if all_complete else "partially_received"
    po.received_at = datetime.now(timezone.utc)
    po.received_by = user_id

    db.session.flush()

    # Auto-post accounting entry
    if total_cost > 0:
        from app.modules.accounting.services import create_journal_entry, calculate_withholdings
        from app.modules.auth_rbac.models import Tenant
        tenant = Tenant.query.get(tenant_id)
        is_simplified = tenant and tenant.fiscal_regime == "simplified"

        # For simplified regime: IVA goes to cost (no deductible IVA)
        inventory_debit = float(total_cost + total_tax) if is_simplified else float(total_cost)

        # Calculate withholdings (ReteFuente, ReteIVA)
        withholdings = calculate_withholdings(tenant_id, total_cost, "purchases")
        total_withholdings = sum(w["amount"] for w in withholdings)

        # Net payable = cost + tax - withholdings
        net_payable = float(total_cost + total_tax) - total_withholdings

        lines = [
            {"puc_code": "1435", "debit": inventory_debit, "credit": 0,
             "description": f"Compra {po.order_number}"},
        ]
        if not is_simplified and total_tax > 0:
            lines.append({"puc_code": "2408", "debit": float(total_tax), "credit": 0,
                          "description": "IVA descontable"})

        # Add withholding lines (credit — liability to DIAN)
        for w in withholdings:
            lines.append({"puc_code": w["puc_code"], "debit": 0, "credit": w["amount"],
                          "description": f"{w['name']} ({w['rate']}%)"})

        if po.payment_type == "cash":
            lines.append({"puc_code": "1105", "debit": 0, "credit": net_payable,
                          "description": "Pago de contado (neto retenciones)"})
        else:
            lines.append({"puc_code": "2205", "debit": 0, "credit": net_payable,
                          "description": "CxP proveedor (neto retenciones)"})

        create_journal_entry(
            tenant_id=tenant_id, created_by=user_id,
            entry_type="PURCHASE", description=f"Recepción {po.order_number}",
            lines=lines,
            source_document_type="purchase_order", source_document_id=str(po.id),
        )

    db.session.commit()
    return _po_to_dict(po)


def cancel_purchase_order(tenant_id: str, po_id: str) -> dict:
    po = _get_po(tenant_id, po_id)
    if po.status not in ("draft", "sent"):
        raise ValueError(f"No se puede cancelar OC en estado: {po.status}")
    po.status = "cancelled"
    po.cancelled_at = datetime.now(timezone.utc)
    db.session.commit()
    return _po_to_dict(po)


def list_purchase_orders(
    tenant_id: str, page: int = 1, per_page: int = 20,
    status: str = None, supplier_id: str = None,
) -> dict:
    q = PurchaseOrder.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    if supplier_id:
        q = q.filter_by(supplier_id=supplier_id)

    total = q.count()
    orders = q.order_by(PurchaseOrder.order_date.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return {
        "data": [_po_summary_to_dict(o) for o in orders],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "has_next": page * per_page < total,
        },
    }


def get_purchase_order(tenant_id: str, po_id: str) -> dict:
    po = _get_po(tenant_id, po_id)
    return _po_to_dict(po)


# ── Supplier Payment Services ─────────────────────────────────────

def _next_payment_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"EGR-{year}-"
    last = (
        db.session.query(func.max(SupplierPayment.payment_number))
        .filter(SupplierPayment.tenant_id == tenant_id,
                SupplierPayment.payment_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def create_supplier_payment(
    tenant_id: str, created_by: str, supplier_id: str,
    amount: float, payment_method: str = "cash",
    purchase_order_id: str = None, reference: str = None,
    bank_account: str = None, notes: str = None,
) -> dict:
    """Register a payment to a supplier. Generates accounting entry: DB 2205 | CR 1105/1110."""
    supplier = Supplier.query.filter_by(id=supplier_id, tenant_id=tenant_id).first()
    if not supplier:
        raise ValueError("Proveedor no encontrado")

    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    if amt <= 0:
        raise ValueError("El monto debe ser mayor a 0")

    payment = SupplierPayment(
        tenant_id=tenant_id, supplier_id=supplier_id, created_by=created_by,
        purchase_order_id=purchase_order_id,
        payment_number=_next_payment_number(tenant_id),
        amount=amt, payment_method=payment_method,
        reference=reference, bank_account=bank_account, notes=notes,
    )
    db.session.add(payment)
    db.session.flush()

    # Accounting entry: DB 2205 Proveedores | CR 1105 Caja or 1110 Bancos
    from app.modules.accounting.services import create_journal_entry
    cash_account = "1105" if payment_method == "cash" else "1110"
    create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="SUPPLIER_PAYMENT",
        description=f"Pago proveedor {supplier.name} - {payment.payment_number}",
        lines=[
            {"puc_code": "2205", "debit": float(amt), "credit": 0,
             "description": f"Pago a {supplier.name}"},
            {"puc_code": cash_account, "debit": 0, "credit": float(amt),
             "description": f"Egreso {payment.payment_number}"},
        ],
        source_document_type="supplier_payment", source_document_id=str(payment.id),
    )

    db.session.commit()
    return _payment_to_dict(payment)


def get_supplier_payments(tenant_id: str, supplier_id: str) -> list:
    payments = SupplierPayment.query.filter_by(
        tenant_id=tenant_id, supplier_id=supplier_id,
    ).order_by(SupplierPayment.created_at.desc()).all()
    return [_payment_to_dict(p) for p in payments]


def get_supplier_balance(tenant_id: str, supplier_id: str) -> dict:
    """Calculate the outstanding CxP balance for a supplier."""
    from sqlalchemy import case

    # Total credit purchases (received POs with payment_type=credit)
    total_purchases = db.session.query(
        func.coalesce(func.sum(PurchaseOrder.total_amount), 0)
    ).filter(
        PurchaseOrder.tenant_id == tenant_id,
        PurchaseOrder.supplier_id == supplier_id,
        PurchaseOrder.payment_type == "credit",
        PurchaseOrder.status.in_(["received", "partially_received"]),
    ).scalar()

    # Total payments
    total_payments = db.session.query(
        func.coalesce(func.sum(SupplierPayment.amount), 0)
    ).filter(
        SupplierPayment.tenant_id == tenant_id,
        SupplierPayment.supplier_id == supplier_id,
        SupplierPayment.status == "completed",
    ).scalar()

    # Total credit notes
    total_credit_notes = db.session.query(
        func.coalesce(func.sum(PurchaseCreditNote.total_amount), 0)
    ).filter(
        PurchaseCreditNote.tenant_id == tenant_id,
        PurchaseCreditNote.supplier_id == supplier_id,
        PurchaseCreditNote.status == "active",
    ).scalar()

    # Total debit notes
    total_debit_notes = db.session.query(
        func.coalesce(func.sum(PurchaseDebitNote.total_amount), 0)
    ).filter(
        PurchaseDebitNote.tenant_id == tenant_id,
        PurchaseDebitNote.supplier_id == supplier_id,
        PurchaseDebitNote.status == "active",
    ).scalar()

    balance = (
        Decimal(str(total_purchases))
        + Decimal(str(total_debit_notes))
        - Decimal(str(total_payments))
        - Decimal(str(total_credit_notes))
    )

    return {
        "supplier_id": supplier_id,
        "total_purchases": float(total_purchases),
        "total_payments": float(total_payments),
        "total_credit_notes": float(total_credit_notes),
        "total_debit_notes": float(total_debit_notes),
        "balance": float(balance),
    }


def void_supplier_payment(tenant_id: str, payment_id: str, user_id: str) -> dict:
    """Void a supplier payment and generate reversal entry."""
    payment = SupplierPayment.query.filter_by(
        id=payment_id, tenant_id=tenant_id
    ).first()
    if not payment:
        raise ValueError("Pago no encontrado")
    if payment.status == "voided":
        raise ValueError("El pago ya fue anulado")

    payment.status = "voided"
    payment.voided_at = datetime.now(timezone.utc)
    payment.voided_by = user_id

    # Reversal entry: DB 1105/1110 | CR 2205
    from app.modules.accounting.services import create_journal_entry
    cash_account = "1105" if payment.payment_method == "cash" else "1110"
    create_journal_entry(
        tenant_id=tenant_id, created_by=user_id,
        entry_type="REVERSAL",
        description=f"Anulación pago {payment.payment_number}",
        lines=[
            {"puc_code": cash_account, "debit": float(payment.amount), "credit": 0,
             "description": "Reversa egreso"},
            {"puc_code": "2205", "debit": 0, "credit": float(payment.amount),
             "description": "Reversa pago proveedor"},
        ],
        source_document_type="supplier_payment_void", source_document_id=str(payment.id),
    )

    db.session.commit()
    return _payment_to_dict(payment)


# ── Purchase Credit Note Services ────────────────────────────────

def _next_pcn_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"NCC-{year}-"
    last = (
        db.session.query(func.max(PurchaseCreditNote.note_number))
        .filter(PurchaseCreditNote.tenant_id == tenant_id,
                PurchaseCreditNote.note_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def create_purchase_credit_note(
    tenant_id: str, created_by: str, supplier_id: str,
    reason: str, items: list, purchase_order_id: str = None,
) -> dict:
    """
    Create a credit note for a purchase (return to supplier).
    Generates inventory movement (return_purchase) and accounting entry.
    items: [{"product_id": str, "quantity": float, "unit_cost": float, "tax_rate": float}]
    """
    supplier = Supplier.query.filter_by(id=supplier_id, tenant_id=tenant_id).first()
    if not supplier:
        raise ValueError("Proveedor no encontrado")

    cn = PurchaseCreditNote(
        tenant_id=tenant_id, supplier_id=supplier_id, created_by=created_by,
        purchase_order_id=purchase_order_id,
        note_number=_next_pcn_number(tenant_id), reason=reason,
        subtotal=0, tax_amount=0, total_amount=0,
    )

    total_sub = Decimal("0")
    total_tax = Decimal("0")

    for item_data in items:
        product = Product.query.filter_by(
            id=item_data["product_id"], tenant_id=tenant_id
        ).with_for_update().first()
        if not product:
            raise ValueError(f"Producto no encontrado: {item_data['product_id']}")

        qty = Decimal(str(item_data["quantity"]))
        cost = Decimal(str(item_data["unit_cost"]))
        rate = Decimal(str(item_data.get("tax_rate", 19.0)))

        line_sub = (qty * cost).quantize(TWO_PLACES)
        line_tax = (line_sub * rate / 100).quantize(TWO_PLACES)

        cn_item = PurchaseCreditNoteItem(
            product_id=product.id, product_name=product.name,
            quantity=qty, unit_cost=cost, tax_rate=rate,
            subtotal=line_sub, tax_amount=line_tax, total=line_sub + line_tax,
        )
        cn.items.append(cn_item)
        total_sub += line_sub
        total_tax += line_tax

        # Inventory movement: return_purchase (stock decreases)
        stock_before = product.stock_current
        product.stock_current -= qty
        movement = StockMovement(
            tenant_id=tenant_id, product_id=product.id, created_by=created_by,
            movement_type="return_purchase", quantity=-qty,
            stock_before=stock_before, stock_after=product.stock_current,
            unit_cost=cost,
            reference_type="purchase_credit_note", reference_id=cn.id,
            reason=reason,
        )
        db.session.add(movement)

    cn.subtotal = total_sub
    cn.tax_amount = total_tax
    cn.total_amount = total_sub + total_tax
    db.session.add(cn)
    db.session.flush()

    # Accounting: DB 2205 | CR 1435 + CR 2370
    from app.modules.accounting.services import create_journal_entry
    lines = [
        {"puc_code": "2205", "debit": float(cn.total_amount), "credit": 0,
         "description": f"NC compra {cn.note_number}"},
        {"puc_code": "1435", "debit": 0, "credit": float(cn.subtotal),
         "description": "Devolución inventario a proveedor"},
    ]
    if total_tax > 0:
        lines.append({
            "puc_code": "2408", "debit": 0, "credit": float(cn.tax_amount),
            "description": "Reversa IVA descontable",
        })

    create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="CREDIT_NOTE_PURCHASE",
        description=f"Nota crédito compra {cn.note_number} - {supplier.name}",
        lines=lines,
        source_document_type="purchase_credit_note", source_document_id=str(cn.id),
    )

    db.session.commit()
    return _pcn_to_dict(cn)


def get_purchase_credit_notes(tenant_id: str, supplier_id: str = None) -> list:
    q = PurchaseCreditNote.query.filter_by(tenant_id=tenant_id)
    if supplier_id:
        q = q.filter_by(supplier_id=supplier_id)
    return [_pcn_to_dict(cn) for cn in q.order_by(PurchaseCreditNote.created_at.desc()).all()]


# ── Purchase Debit Note Services ─────────────────────────────────

def _next_pdn_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"NDC-{year}-"
    last = (
        db.session.query(func.max(PurchaseDebitNote.note_number))
        .filter(PurchaseDebitNote.tenant_id == tenant_id,
                PurchaseDebitNote.note_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def create_purchase_debit_note(
    tenant_id: str, created_by: str, supplier_id: str,
    reason: str, amount: float, tax_amount: float = 0,
    purchase_order_id: str = None,
) -> dict:
    """Create a debit note (additional charges from supplier: freight, interest)."""
    supplier = Supplier.query.filter_by(id=supplier_id, tenant_id=tenant_id).first()
    if not supplier:
        raise ValueError("Proveedor no encontrado")

    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    tax = Decimal(str(tax_amount)).quantize(TWO_PLACES)
    total = amt + tax

    dn = PurchaseDebitNote(
        tenant_id=tenant_id, supplier_id=supplier_id, created_by=created_by,
        purchase_order_id=purchase_order_id,
        note_number=_next_pdn_number(tenant_id), reason=reason,
        amount=amt, tax_amount=tax, total_amount=total,
    )
    db.session.add(dn)
    db.session.flush()

    # Accounting: DB 5195 Gastos diversos | CR 2205 Proveedores
    from app.modules.accounting.services import create_journal_entry
    create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="DEBIT_NOTE",
        description=f"ND compra {dn.note_number} - {supplier.name}: {reason}",
        lines=[
            {"puc_code": "5195", "debit": float(total), "credit": 0,
             "description": reason},
            {"puc_code": "2205", "debit": 0, "credit": float(total),
             "description": f"Cargo proveedor {supplier.name}"},
        ],
        source_document_type="purchase_debit_note", source_document_id=str(dn.id),
    )

    db.session.commit()
    return _pdn_to_dict(dn)


# ── Helpers ───────────────────────────────────────────────────────

def _get_po(tenant_id: str, po_id: str) -> PurchaseOrder:
    po = PurchaseOrder.query.filter_by(id=po_id, tenant_id=tenant_id).first()
    if not po:
        raise ValueError("Orden de compra no encontrada")
    return po


# ── Serializers ───────────────────────────────────────────────────

def _supplier_to_dict(s: Supplier) -> dict:
    return {
        "id": str(s.id), "name": s.name, "tax_id": s.tax_id,
        "contact_name": s.contact_name, "phone": s.phone,
        "email": s.email, "city": s.city,
        "payment_terms_days": s.payment_terms_days,
        "is_active": s.is_active,
    }


def _po_to_dict(po: PurchaseOrder) -> dict:
    return {
        "id": str(po.id), "order_number": po.order_number,
        "supplier_name": po.supplier.name if po.supplier else None,
        "order_date": po.order_date.isoformat(),
        "status": po.status, "payment_type": po.payment_type,
        "subtotal": float(po.subtotal), "tax_amount": float(po.tax_amount),
        "total_amount": float(po.total_amount),
        "supplier_invoice": po.supplier_invoice,
        "items": [_po_item_to_dict(i) for i in po.items],
        "received_at": po.received_at.isoformat() if po.received_at else None,
    }


def _po_summary_to_dict(po: PurchaseOrder) -> dict:
    return {
        "id": str(po.id), "order_number": po.order_number,
        "supplier_name": po.supplier.name if po.supplier else None,
        "status": po.status, "total_amount": float(po.total_amount),
        "order_date": po.order_date.isoformat(),
        "items_count": len(po.items),
    }


def _po_item_to_dict(i: PurchaseOrderItem) -> dict:
    return {
        "id": str(i.id), "product_id": str(i.product_id), "product_name": i.product_name,
        "quantity_ordered": float(i.quantity_ordered),
        "quantity_received": float(i.quantity_received),
        "unit_cost": float(i.unit_cost), "tax_rate": float(i.tax_rate),
        "subtotal": float(i.subtotal), "total": float(i.total),
    }


def get_purchase_debit_notes(tenant_id: str, supplier_id: str = None) -> list:
    q = PurchaseDebitNote.query.filter_by(tenant_id=tenant_id)
    if supplier_id:
        q = q.filter_by(supplier_id=supplier_id)
    return [_pdn_to_dict(dn) for dn in q.order_by(PurchaseDebitNote.created_at.desc()).all()]


def _payment_to_dict(p: SupplierPayment) -> dict:
    return {
        "id": str(p.id),
        "payment_number": p.payment_number,
        "supplier_id": str(p.supplier_id),
        "supplier_name": p.supplier.name if p.supplier else None,
        "amount": float(p.amount),
        "payment_method": p.payment_method,
        "payment_date": p.payment_date.isoformat(),
        "reference": p.reference,
        "status": p.status,
        "notes": p.notes,
        "created_at": p.created_at.isoformat(),
    }


def _pcn_to_dict(cn: PurchaseCreditNote) -> dict:
    return {
        "id": str(cn.id),
        "note_number": cn.note_number,
        "supplier_id": str(cn.supplier_id),
        "supplier_name": cn.supplier.name if cn.supplier else None,
        "reason": cn.reason,
        "subtotal": float(cn.subtotal),
        "tax_amount": float(cn.tax_amount),
        "total_amount": float(cn.total_amount),
        "status": cn.status,
        "items": [{
            "product_name": i.product_name,
            "quantity": float(i.quantity),
            "unit_cost": float(i.unit_cost),
            "subtotal": float(i.subtotal),
            "total": float(i.total),
        } for i in cn.items],
        "created_at": cn.created_at.isoformat(),
    }


def _pdn_to_dict(dn: PurchaseDebitNote) -> dict:
    return {
        "id": str(dn.id),
        "note_number": dn.note_number,
        "supplier_id": str(dn.supplier_id),
        "supplier_name": dn.supplier.name if dn.supplier else None,
        "reason": dn.reason,
        "amount": float(dn.amount),
        "tax_amount": float(dn.tax_amount),
        "total_amount": float(dn.total_amount),
        "status": dn.status,
        "created_at": dn.created_at.isoformat(),
    }
