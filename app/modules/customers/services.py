"""Customer services — CRUD, payments, debit notes, aging report."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.modules.customers.models import (
    CollectionCampaign,
    CollectionCampaignItem,
    Customer,
    CustomerPayment,
    SalesDebitNote,
)
from app.modules.pos.models import Sale

TWO_PLACES = Decimal("0.01")


def create_customer(
    tenant_id: str,
    created_by: str,
    name: str,
    tax_id: str = None,
    tax_id_type: str = "CC",
    contact_name: str = None,
    phone: str = None,
    email: str = None,
    address: str = None,
    city: str = None,
    credit_limit: float = 0,
    credit_days: int = 0,
    notes: str = None,
) -> dict:
    customer = Customer(
        tenant_id=tenant_id,
        created_by=created_by,
        name=name,
        tax_id=tax_id,
        tax_id_type=tax_id_type,
        contact_name=contact_name,
        phone=phone,
        email=email,
        address=address,
        city=city,
        credit_limit=credit_limit,
        credit_days=credit_days,
        notes=notes,
    )
    db.session.add(customer)
    db.session.commit()
    return _customer_to_dict(customer)


def get_customers(tenant_id: str, search: str = None) -> list:
    q = Customer.query.filter(
        Customer.tenant_id == tenant_id,
        Customer.is_active.is_(True),
        Customer.deleted_at.is_(None),
    )
    if search:
        q = q.filter(
            db.or_(
                Customer.name.ilike(f"%{search}%"),
                Customer.tax_id.ilike(f"%{search}%"),
                Customer.phone.ilike(f"%{search}%"),
            )
        )
    return [_customer_to_dict(c) for c in q.order_by(Customer.name).all()]


def get_customer(tenant_id: str, customer_id: str) -> dict:
    c = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not c:
        raise ValueError("Cliente no encontrado")
    return _customer_to_dict(c)


def update_customer(tenant_id: str, customer_id: str, **kwargs) -> dict:
    c = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not c:
        raise ValueError("Cliente no encontrado")
    allowed = {
        "name",
        "tax_id",
        "tax_id_type",
        "contact_name",
        "phone",
        "email",
        "address",
        "city",
        "credit_limit",
        "credit_days",
        "notes",
    }
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            setattr(c, k, v)
    db.session.commit()
    return _customer_to_dict(c)


# ── Customer Payment Services ─────────────────────────────────────


def _next_cp_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"AB-{year}-"
    last = (
        db.session.query(func.max(CustomerPayment.payment_number))
        .filter(CustomerPayment.tenant_id == tenant_id, CustomerPayment.payment_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def create_customer_payment(
    tenant_id: str,
    created_by: str,
    customer_id: str,
    amount: float,
    payment_method: str = "cash",
    sale_id: str = None,
    reference: str = None,
    notes: str = None,
) -> dict:
    """Register a payment from a customer. Updates sale balances if linked."""
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        raise ValueError("Cliente no encontrado")

    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    if amt <= 0:
        raise ValueError("El monto debe ser mayor a 0")

    payment = CustomerPayment(
        tenant_id=tenant_id,
        customer_id=customer_id,
        created_by=created_by,
        sale_id=sale_id,
        payment_number=_next_cp_number(tenant_id),
        amount=amt,
        payment_method=payment_method,
        reference=reference,
        notes=notes,
    )
    db.session.add(payment)
    db.session.flush()

    # Update linked sale if provided
    if sale_id:
        sale = Sale.query.filter_by(id=sale_id, tenant_id=tenant_id).first()
        if sale and sale.sale_type == "credit":
            sale.amount_paid = (Decimal(str(sale.amount_paid)) + amt).quantize(TWO_PLACES)
            sale.amount_due = (Decimal(str(sale.total_amount)) - Decimal(str(sale.amount_paid))).quantize(TWO_PLACES)
            if sale.amount_due <= 0:
                sale.payment_status = "paid"
                sale.amount_due = Decimal("0")
            else:
                sale.payment_status = "partial"

    # Accounting: DB 1105 Caja | CR 1305 Clientes
    from app.modules.accounting.services import create_journal_entry

    cash_account = "1105" if payment_method == "cash" else "1110"
    create_journal_entry(
        tenant_id=tenant_id,
        created_by=created_by,
        entry_type="CASH_RECEIPT",
        description=f"Abono cliente {customer.name} - {payment.payment_number}",
        lines=[
            {"puc_code": cash_account, "debit": float(amt), "credit": 0, "description": f"Cobro a {customer.name}"},
            {"puc_code": "1305", "debit": 0, "credit": float(amt), "description": f"Abono cliente {customer.name}"},
        ],
        source_document_type="customer_payment",
        source_document_id=str(payment.id),
    )

    # Auto-update campaign items if this customer/sale is in an active campaign
    try:
        active_items = CollectionCampaignItem.query.join(CollectionCampaign).filter(
            CollectionCampaign.tenant_id == tenant_id,
            CollectionCampaign.status == "active",
            CollectionCampaignItem.customer_id == customer_id,
            CollectionCampaignItem.contact_status.in_(["pending", "contacted", "promised"]),
        )
        if sale_id:
            active_items = active_items.filter(CollectionCampaignItem.sale_id == sale_id)
        for item in active_items.all():
            item.contact_status = "paid"
            item.contact_date = datetime.now(timezone.utc)
    except Exception:
        pass

    db.session.commit()
    return _cp_to_dict(payment)


def get_customer_payments(tenant_id: str, customer_id: str) -> list:
    payments = (
        CustomerPayment.query.filter_by(
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
        .order_by(CustomerPayment.created_at.desc())
        .all()
    )
    return [_cp_to_dict(p) for p in payments]


def get_customer_statement(tenant_id: str, customer_id: str) -> dict:
    """Get full statement: credit sales, payments, debit notes, balance."""
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        raise ValueError("Cliente no encontrado")

    # Credit sales
    credit_sales = (
        Sale.query.filter(
            Sale.tenant_id == tenant_id,
            Sale.customer_id == customer_id,
            Sale.sale_type == "credit",
            Sale.status == "completed",
        )
        .order_by(Sale.sale_date.desc())
        .all()
    )

    total_sales = sum(float(s.total_amount) for s in credit_sales)
    total_paid = sum(float(s.amount_paid) for s in credit_sales)
    total_due = sum(float(s.amount_due) for s in credit_sales)

    return {
        "customer": _customer_to_dict(customer),
        "total_credit_sales": total_sales,
        "total_paid": total_paid,
        "total_due": total_due,
        "sales": [
            {
                "id": str(s.id),
                "invoice_number": s.invoice_number,
                "date": s.sale_date.isoformat(),
                "total": float(s.total_amount),
                "paid": float(s.amount_paid),
                "due": float(s.amount_due),
                "status": s.payment_status,
                "due_date": s.due_date.isoformat() if s.due_date else None,
            }
            for s in credit_sales
        ],
    }


def get_aging_report(tenant_id: str) -> dict:
    """Aging report: categorize outstanding CxC by age."""
    now = datetime.now(timezone.utc)
    sales = Sale.query.filter(
        Sale.tenant_id == tenant_id,
        Sale.sale_type == "credit",
        Sale.status == "completed",
        Sale.payment_status.in_(["pending", "partial", "overdue"]),
    ).all()

    buckets = {"0_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
    total = Decimal("0")
    items = []

    for sale in sales:
        due = Decimal(str(sale.amount_due))
        total += due
        days = (now - (sale.due_date or sale.sale_date)).days
        if days <= 30:
            buckets["0_30"] += float(due)
        elif days <= 60:
            buckets["31_60"] += float(due)
        elif days <= 90:
            buckets["61_90"] += float(due)
        else:
            buckets["over_90"] += float(due)
        items.append(
            {
                "customer_name": sale.customer_name,
                "invoice": sale.invoice_number,
                "amount_due": float(due),
                "days": days,
                "due_date": sale.due_date.isoformat() if sale.due_date else None,
            }
        )

    return {
        "total_outstanding": float(total),
        "buckets": buckets,
        "items": sorted(items, key=lambda x: x["days"], reverse=True),
    }


def write_off_customer(tenant_id: str, customer_id: str, user_id: str, sale_id: str = None) -> dict:
    """Write off uncollectable debt. DB 5195 Gastos diversos | CR 1305 Clientes."""
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        raise ValueError("Cliente no encontrado")

    if sale_id:
        sales = [Sale.query.filter_by(id=sale_id, tenant_id=tenant_id).first()]
    else:
        sales = Sale.query.filter(
            Sale.tenant_id == tenant_id,
            Sale.customer_id == customer_id,
            Sale.sale_type == "credit",
            Sale.payment_status.in_(["pending", "partial", "overdue"]),
        ).all()

    total_writeoff = Decimal("0")
    for sale in sales:
        if sale and sale.amount_due > 0:
            total_writeoff += Decimal(str(sale.amount_due))
            sale.amount_paid = sale.total_amount
            sale.amount_due = 0
            sale.payment_status = "paid"

    if total_writeoff <= 0:
        raise ValueError("No hay saldo pendiente para castigar")

    from app.modules.accounting.services import create_journal_entry

    create_journal_entry(
        tenant_id=tenant_id,
        created_by=user_id,
        entry_type="ADJUSTMENT",
        description=f"Castigo cartera - {customer.name}",
        lines=[
            {
                "puc_code": "5195",
                "debit": float(total_writeoff),
                "credit": 0,
                "description": f"Cartera incobrable {customer.name}",
            },
            {"puc_code": "1305", "debit": 0, "credit": float(total_writeoff), "description": "Castigo cuenta cliente"},
        ],
        source_document_type="write_off",
        source_document_id=str(customer_id),
    )

    db.session.commit()
    return {"written_off": float(total_writeoff), "customer": customer.name}


# ── Sales Debit Note Services ────────────────────────────────────


def _next_sdn_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"NDV-{year}-"
    last = (
        db.session.query(func.max(SalesDebitNote.note_number))
        .filter(SalesDebitNote.tenant_id == tenant_id, SalesDebitNote.note_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def create_sales_debit_note(
    tenant_id: str,
    created_by: str,
    customer_id: str,
    reason: str,
    amount: float,
    tax_amount: float = 0,
    sale_id: str = None,
) -> dict:
    """Create a debit note against a customer (interest, additional charges).
    Asiento: DB 1305 Clientes | CR 4135 Ingresos + CR 2408 IVA
    """
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        raise ValueError("Cliente no encontrado")

    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    tax = Decimal(str(tax_amount)).quantize(TWO_PLACES)
    total = amt + tax

    dn = SalesDebitNote(
        tenant_id=tenant_id,
        customer_id=customer_id,
        created_by=created_by,
        sale_id=sale_id,
        note_number=_next_sdn_number(tenant_id),
        reason=reason,
        amount=amt,
        tax_amount=tax,
        total_amount=total,
    )
    db.session.add(dn)
    db.session.flush()

    # Update linked sale amount_due if provided
    if sale_id:
        sale = Sale.query.filter_by(id=sale_id, tenant_id=tenant_id).first()
        if sale and sale.sale_type == "credit":
            sale.amount_due = (Decimal(str(sale.amount_due)) + total).quantize(TWO_PLACES)
            if sale.payment_status == "paid":
                sale.payment_status = "pending"

    # Accounting: DB 1305 Clientes | CR 4135 Ingresos + CR 2408 IVA
    from app.modules.accounting.services import create_journal_entry

    lines = [
        {
            "puc_code": "1305",
            "debit": float(total),
            "credit": 0,
            "description": f"ND {dn.note_number} - {customer.name}: {reason}",
        },
        {"puc_code": "4135", "debit": 0, "credit": float(amt), "description": "Ingreso por cargo adicional"},
    ]
    if tax > 0:
        lines.append(
            {
                "puc_code": "2408",
                "debit": 0,
                "credit": float(tax),
                "description": "IVA generado",
            }
        )

    create_journal_entry(
        tenant_id=tenant_id,
        created_by=created_by,
        entry_type="SALES_DEBIT_NOTE",
        description=f"Nota débito venta {dn.note_number}: {reason}",
        lines=lines,
        source_document_type="sales_debit_note",
        source_document_id=str(dn.id),
    )

    db.session.commit()
    return _sdn_to_dict(dn)


def get_sales_debit_notes(tenant_id: str, customer_id: str = None) -> list:
    q = SalesDebitNote.query.filter_by(tenant_id=tenant_id)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    return [_sdn_to_dict(dn) for dn in q.order_by(SalesDebitNote.created_at.desc()).all()]


# ── Serializers ──────────────────────────────────────────────────

# ── Collection Campaign Services ──────────────────────────────────


def _next_campaign_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"COB-{year}-"
    last = (
        db.session.query(func.max(CollectionCampaign.campaign_number))
        .filter(CollectionCampaign.tenant_id == tenant_id, CollectionCampaign.campaign_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def create_collection_campaign(
    tenant_id: str,
    created_by: str,
    name: str,
    target_type: str = "all_overdue",
    min_days_overdue: int = 1,
    min_amount_due: float = 0,
    message_template: str = None,
) -> dict:
    """Create a collection campaign and populate it with overdue customers."""
    now = datetime.now(timezone.utc)

    # Auto-mark overdue sales first
    try:
        from app.modules.pos.services import mark_overdue_sales

        mark_overdue_sales(tenant_id)
    except Exception:
        pass

    default_msg = (
        "Estimado(a) {nombre}, le recordamos que tiene un saldo pendiente de ${monto} "
        "con {dias} días de vencimiento. Agradecemos su pronto pago. — {negocio}"
    )

    campaign = CollectionCampaign(
        tenant_id=tenant_id,
        created_by=created_by,
        campaign_number=_next_campaign_number(tenant_id),
        name=name,
        target_type=target_type,
        min_days_overdue=min_days_overdue,
        min_amount_due=Decimal(str(min_amount_due)),
        message_template=message_template or default_msg,
    )
    db.session.add(campaign)
    db.session.flush()

    # Find overdue credit sales
    overdue_sales = Sale.query.filter(
        Sale.tenant_id == tenant_id,
        Sale.sale_type == "credit",
        Sale.status == "completed",
        Sale.payment_status.in_(["pending", "partial", "overdue"]),
        Sale.amount_due > min_amount_due,
    ).all()

    total_customers = set()
    total_amount = Decimal("0")

    for sale in overdue_sales:
        days = (now - (sale.due_date or sale.sale_date)).days
        if days < min_days_overdue:
            continue
        if not sale.customer_id:
            continue

        item = CollectionCampaignItem(
            customer_id=sale.customer_id,
            sale_id=sale.id,
            amount_due=sale.amount_due,
            days_overdue=days,
        )
        campaign.items.append(item)
        total_customers.add(str(sale.customer_id))
        total_amount += Decimal(str(sale.amount_due))

    campaign.total_customers = len(total_customers)
    campaign.total_amount_targeted = total_amount

    db.session.commit()
    return _campaign_to_dict(campaign)


def get_collection_campaigns(tenant_id: str) -> list:
    campaigns = (
        CollectionCampaign.query.filter_by(tenant_id=tenant_id).order_by(CollectionCampaign.created_at.desc()).all()
    )
    return [_campaign_summary_to_dict(c) for c in campaigns]


def get_collection_campaign(tenant_id: str, campaign_id: str) -> dict:
    c = CollectionCampaign.query.filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not c:
        raise ValueError("Campaña no encontrada")

    # Auto-regenerate rendered_message if missing (migration or data issue)
    if c.status == "active" and c.message_template:
        from app.modules.auth_rbac.models import Tenant

        tenant = Tenant.query.get(tenant_id)
        tenant_name = tenant.name if tenant else "Nuestro negocio"
        needs_save = False
        for item in c.items:
            if not item.rendered_message:
                customer = item.customer
                msg = c.message_template
                msg = msg.replace("{nombre}", customer.name if customer else "Cliente")
                msg = msg.replace("{monto}", f"{float(item.amount_due):,.0f}")
                msg = msg.replace("{dias}", str(item.days_overdue))
                msg = msg.replace("{negocio}", tenant_name)
                item.rendered_message = msg
                needs_save = True
        if needs_save:
            db.session.commit()

    return _campaign_to_dict(c)


def update_campaign_item(tenant_id: str, campaign_id: str, item_id: str, **kwargs) -> dict:
    """Update the contact status of a campaign item."""
    c = CollectionCampaign.query.filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not c:
        raise ValueError("Campaña no encontrada")

    item = CollectionCampaignItem.query.filter_by(id=item_id, campaign_id=campaign_id).first()
    if not item:
        raise ValueError("Item no encontrado")

    for field in ("contact_status", "contact_method", "contact_date", "promise_date", "notes"):
        if field in kwargs and kwargs[field] is not None:
            setattr(item, field, kwargs[field])

    if kwargs.get("contact_status") in ("contacted", "promised", "paid", "failed"):
        if not item.contact_date:
            item.contact_date = datetime.now(timezone.utc)

    db.session.commit()
    return _campaign_item_to_dict(item)


def execute_campaign(tenant_id: str, campaign_id: str) -> dict:
    """Execute campaign: render personalized messages for each customer and activate."""
    from app.modules.auth_rbac.models import Tenant

    c = CollectionCampaign.query.filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not c:
        raise ValueError("Campaña no encontrada")
    if c.status != "draft":
        raise ValueError(f"Campaña en estado {c.status}, solo se puede activar en draft")

    tenant = Tenant.query.get(tenant_id)
    tenant_name = tenant.name if tenant else "Nuestro negocio"
    template = c.message_template or ""

    for item in c.items:
        customer = item.customer
        # Render message with variables
        msg = template.replace("{nombre}", customer.name if customer else "Cliente")
        msg = msg.replace("{monto}", f"{float(item.amount_due):,.0f}")
        msg = msg.replace("{dias}", str(item.days_overdue))
        msg = msg.replace("{negocio}", tenant_name)
        item.rendered_message = msg
        item.contact_status = "pending"

    c.status = "active"
    c.executed_at = datetime.now(timezone.utc)
    db.session.commit()
    return _campaign_to_dict(c)


def cancel_campaign(tenant_id: str, campaign_id: str) -> dict:
    """Cancel an active or draft campaign."""
    c = CollectionCampaign.query.filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not c:
        raise ValueError("Campaña no encontrada")
    if c.status in ("completed", "cancelled"):
        raise ValueError(f"Campaña ya está {c.status}")
    c.status = "cancelled"
    db.session.commit()
    return _campaign_to_dict(c)


def complete_campaign(tenant_id: str, campaign_id: str) -> dict:
    """Mark campaign as completed."""
    c = CollectionCampaign.query.filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not c:
        raise ValueError("Campaña no encontrada")
    if c.status != "active":
        raise ValueError("Solo se pueden completar campañas activas")
    c.status = "completed"
    db.session.commit()
    return _campaign_to_dict(c)


# ── Campaign Serializers ─────────────────────────────────────────


def _campaign_to_dict(c: CollectionCampaign) -> dict:
    # Count statuses and calculate effectiveness
    statuses = {}
    total_collected = Decimal("0")
    for item in c.items:
        statuses[item.contact_status] = statuses.get(item.contact_status, 0) + 1
        if item.contact_status == "paid":
            total_collected += Decimal(str(item.amount_due))

    total_target = Decimal(str(c.total_amount_targeted)) if c.total_amount_targeted else Decimal("0")
    effectiveness = round(float(total_collected / total_target * 100), 1) if total_target > 0 else 0

    return {
        "id": str(c.id),
        "campaign_number": c.campaign_number,
        "name": c.name,
        "target_type": c.target_type,
        "min_days_overdue": c.min_days_overdue,
        "min_amount_due": float(c.min_amount_due),
        "message_template": c.message_template,
        "status": c.status,
        "total_customers": c.total_customers,
        "total_amount_targeted": float(c.total_amount_targeted),
        "total_collected": float(total_collected),
        "effectiveness_pct": effectiveness,
        "status_summary": statuses,
        "items": [_campaign_item_to_dict(i) for i in c.items],
        "created_at": c.created_at.isoformat(),
    }


def _campaign_summary_to_dict(c: CollectionCampaign) -> dict:
    return {
        "id": str(c.id),
        "campaign_number": c.campaign_number,
        "name": c.name,
        "status": c.status,
        "total_customers": c.total_customers,
        "total_amount_targeted": float(c.total_amount_targeted),
        "created_at": c.created_at.isoformat(),
    }


def _campaign_item_to_dict(i: CollectionCampaignItem) -> dict:
    customer = i.customer
    return {
        "id": str(i.id),
        "customer_id": str(i.customer_id),
        "customer_name": customer.name if customer else None,
        "customer_phone": customer.phone if customer else None,
        "customer_email": customer.email if customer else None,
        "sale_id": str(i.sale_id) if i.sale_id else None,
        "amount_due": float(i.amount_due),
        "days_overdue": i.days_overdue,
        "contact_method": i.contact_method,
        "contact_status": i.contact_status,
        "contact_date": i.contact_date.isoformat() if i.contact_date else None,
        "promise_date": i.promise_date.isoformat() if i.promise_date else None,
        "rendered_message": i.rendered_message,
        "notes": i.notes,
    }


def _sdn_to_dict(dn: SalesDebitNote) -> dict:
    return {
        "id": str(dn.id),
        "note_number": dn.note_number,
        "customer_id": str(dn.customer_id),
        "customer_name": dn.customer.name if dn.customer else None,
        "reason": dn.reason,
        "amount": float(dn.amount),
        "tax_amount": float(dn.tax_amount),
        "total_amount": float(dn.total_amount),
        "status": dn.status,
        "created_at": dn.created_at.isoformat(),
    }


def _cp_to_dict(p: CustomerPayment) -> dict:
    return {
        "id": str(p.id),
        "payment_number": p.payment_number,
        "customer_id": str(p.customer_id),
        "customer_name": p.customer.name if p.customer else None,
        "sale_id": str(p.sale_id) if p.sale_id else None,
        "amount": float(p.amount),
        "payment_method": p.payment_method,
        "reference": p.reference,
        "status": p.status,
        "payment_date": p.payment_date.isoformat(),
    }


def build_collection_letter_data(tenant_id: str, customer_id: str) -> dict:
    """Build all data needed for a formal collection letter."""
    from app.modules.auth_rbac.models import Tenant

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        raise ValueError("Tenant no encontrado")

    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        raise ValueError("Cliente no encontrado")

    # Get overdue credit sales
    overdue_sales = (
        Sale.query.filter(
            Sale.tenant_id == tenant_id,
            Sale.customer_id == customer_id,
            Sale.sale_type == "credit",
            Sale.status == "completed",
            Sale.payment_status.in_(["pending", "partial", "overdue"]),
        )
        .order_by(Sale.due_date)
        .all()
    )

    now = datetime.now(timezone.utc)
    invoices = []
    total_due = Decimal("0")
    max_days = 0
    for s in overdue_sales:
        due = float(s.amount_due or s.total_amount)
        if due <= 0:
            continue
        days = (now - (s.due_date or s.sale_date)).days if (s.due_date or s.sale_date) else 0
        if days < 0:
            days = 0
        if days > max_days:
            max_days = days
        invoices.append(
            {
                "number": s.invoice_number,
                "due_date": (s.due_date or s.sale_date).strftime("%d/%m/%Y") if (s.due_date or s.sale_date) else "—",
                "original_amount": float(s.total_amount),
                "balance_due": due,
            }
        )
        total_due += Decimal(str(due))

    seq = CollectionCampaign.query.filter_by(tenant_id=tenant_id).count() + 1

    return {
        "letter_ref": f"COBRO-{now.year}-{seq:06d}",
        "business_name": tenant.trade_name or tenant.name,
        "business_nit": tenant.tax_id or "—",
        "business_address": tenant.address or "",
        "business_city": tenant.city or "",
        "business_phone": tenant.phone or "",
        "business_email": tenant.email or "",
        "customer_name": customer.name,
        "customer_tax_id": customer.tax_id or "—",
        "customer_tax_id_type": customer.tax_id_type or "CC",
        "customer_city": customer.city or "",
        "invoices": invoices,
        "total_due": float(total_due),
        "days_overdue": max_days,
        "suggested_due_date": (now + timedelta(days=15)).strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%d/%m/%Y %H:%M"),
        "generated_at_long": now.strftime("%d de %B de %Y")
        .replace("January", "enero")
        .replace("February", "febrero")
        .replace("March", "marzo")
        .replace("April", "abril")
        .replace("May", "mayo")
        .replace("June", "junio")
        .replace("July", "julio")
        .replace("August", "agosto")
        .replace("September", "septiembre")
        .replace("October", "octubre")
        .replace("November", "noviembre")
        .replace("December", "diciembre"),
    }


def _customer_to_dict(c: Customer) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "tax_id": c.tax_id,
        "tax_id_type": c.tax_id_type,
        "contact_name": c.contact_name,
        "phone": c.phone,
        "email": c.email,
        "address": c.address,
        "city": c.city,
        "credit_limit": float(c.credit_limit),
        "credit_days": c.credit_days,
        "is_active": c.is_active,
    }
