"""Voucher services — CRUD, emit, sell, redeem, expire. ACID transactions."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from flask import request as flask_request
from sqlalchemy import func
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.modules.vouchers.exceptions import (
    VoucherAlreadyRedeemedError,
    VoucherCancelledError,
    VoucherConcurrencyError,
    VoucherExpiredError,
    VoucherHighValueRequiresIdError,
    VoucherInsufficientBalanceError,
    VoucherInvalidCodeError,
    VoucherMaxIssuedError,
    VoucherNotFoundError,
    VoucherNotSoldError,
    VoucherPrintLimitError,
    VoucherTypeInactiveError,
)
from app.modules.vouchers.models import Voucher, VoucherTransaction, VoucherType
from app.modules.vouchers.security import (
    MAX_CODE_GENERATION_RETRIES,
    generate_voucher_code,
    verify_voucher_code_format,
)

TWO_PLACES = Decimal("0.01")
HIGH_VALUE_THRESHOLD = Decimal("2000000")  # COP — SARLAFT threshold
MAX_PRINT_COUNT = 3


# ── VoucherType CRUD ─────────────────────────────────────────────


def create_voucher_type(
    tenant_id: str,
    created_by: str,
    name: str,
    face_value: float,
    validity_days: int,
    max_issuable: int = None,
    color_hex: str = None,
    design_template: str = "default",
    notes: str = None,
) -> dict:
    """Create a new voucher type (template)."""
    import bleach

    safe_name = bleach.clean(name, tags=[], strip=True)[:100]

    if validity_days < 90:
        raise ValueError("La vigencia mínima es de 90 días")
    if face_value <= 0:
        raise ValueError("El valor nominal debe ser mayor a 0")

    vt = VoucherType(
        tenant_id=tenant_id,
        name=safe_name,
        face_value=Decimal(str(face_value)),
        validity_days=validity_days,
        max_issuable=max_issuable,
        color_hex=color_hex,
        design_template=design_template or "default",
        notes=notes,
        created_by=created_by,
    )
    db.session.add(vt)
    db.session.commit()
    return _voucher_type_to_dict(vt)


def list_voucher_types(tenant_id: str, include_inactive: bool = False) -> list:
    """List all voucher types for a tenant."""
    q = VoucherType.query.filter_by(tenant_id=tenant_id, deleted_at=None)
    if not include_inactive:
        q = q.filter_by(status="active")
    types = q.order_by(VoucherType.created_at.desc()).all()
    return [_voucher_type_to_dict(vt) for vt in types]


def update_voucher_type(tenant_id: str, type_id: str, updated_by: str, **kwargs) -> dict:
    """Update a voucher type. Cannot change face_value if vouchers have been issued."""
    vt = VoucherType.query.filter_by(id=type_id, tenant_id=tenant_id, deleted_at=None).first()
    if not vt:
        raise VoucherNotFoundError("Tipo de bono no encontrado")

    if "face_value" in kwargs and vt.issued_count > 0:
        raise ValueError("No se puede cambiar el valor nominal si ya hay bonos emitidos")

    import bleach

    for key, value in kwargs.items():
        if key == "name":
            value = bleach.clean(value, tags=[], strip=True)[:100]
        if hasattr(vt, key):
            setattr(vt, key, value)

    vt.updated_by = updated_by
    vt.version += 1
    db.session.commit()
    return _voucher_type_to_dict(vt)


def delete_voucher_type(tenant_id: str, type_id: str, deleted_by: str) -> dict:
    """Soft delete a voucher type."""
    vt = VoucherType.query.filter_by(id=type_id, tenant_id=tenant_id, deleted_at=None).first()
    if not vt:
        raise VoucherNotFoundError("Tipo de bono no encontrado")

    vt.deleted_at = datetime.now(timezone.utc)
    vt.status = "inactive"
    vt.updated_by = deleted_by
    db.session.commit()
    return _voucher_type_to_dict(vt)


# ── Voucher Emission ─────────────────────────────────────────────


def emit_voucher(
    tenant_id: str,
    type_id: str,
    created_by: str,
    idempotency_key: str = None,
) -> dict:
    """Emit a single voucher from a voucher type template."""
    if idempotency_key:
        existing = Voucher.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return _voucher_to_dict(existing)

    vt = VoucherType.query.filter_by(id=type_id, tenant_id=tenant_id, deleted_at=None).with_for_update().first()

    if not vt:
        raise VoucherNotFoundError("Tipo de bono no encontrado")
    if not vt.is_active:
        raise VoucherTypeInactiveError()
    if not vt.can_issue:
        raise VoucherMaxIssuedError()

    # Generate unique code with retry
    code = None
    for _ in range(MAX_CODE_GENERATION_RETRIES):
        candidate = generate_voucher_code(str(tenant_id))
        if not Voucher.query.filter_by(code=candidate).first():
            code = candidate
            break
    if not code:
        raise RuntimeError("No se pudo generar un código único para el bono")

    now = datetime.now(timezone.utc)
    voucher = Voucher(
        tenant_id=tenant_id,
        voucher_type_id=vt.id,
        code=code,
        status="issued",
        face_value=vt.face_value,
        remaining_balance=vt.face_value,
        issued_at=now,
        expires_at=now + timedelta(days=vt.validity_days),
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        created_by=created_by,
    )
    db.session.add(voucher)

    vt.issued_count += 1
    vt.version += 1

    db.session.flush()

    # Log transaction
    _log_transaction(
        voucher=voucher,
        transaction_type="issued",
        amount_change=vt.face_value,
        performed_by=created_by,
        notes="Bono emitido",
    )

    db.session.commit()
    return _voucher_to_dict(voucher)


def emit_batch(
    tenant_id: str,
    type_id: str,
    quantity: int,
    created_by: str,
) -> list:
    """Emit multiple vouchers from a voucher type template."""
    if quantity < 1 or quantity > 200:
        raise ValueError("La cantidad debe ser entre 1 y 200")

    results = []
    for i in range(quantity):
        v = emit_voucher(
            tenant_id=tenant_id,
            type_id=type_id,
            created_by=created_by,
            idempotency_key=f"batch-{type_id}-{created_by}-{i}-{uuid.uuid4().hex[:8]}",
        )
        results.append(v)
    return results


# ── Voucher Sale (POS) ───────────────────────────────────────────


def sell_voucher(
    tenant_id: str,
    code: str,
    sale_id: str,
    cashier_id: str,
    idempotency_key: str,
    buyer_name: str = None,
    buyer_customer_id: str = None,
    buyer_id_document: str = None,
) -> dict:
    """
    Mark a voucher as sold within a POS transaction.
    Called inside the checkout atomic transaction.
    Returns accounting data for the caller to create the journal entry.
    """
    code = code.upper().strip()

    # HMAC verification before DB query
    if not verify_voucher_code_format(code, str(tenant_id)):
        raise VoucherInvalidCodeError()

    try:
        voucher = Voucher.query.filter_by(code=code, tenant_id=tenant_id).with_for_update(nowait=True).first()
    except OperationalError:
        raise VoucherConcurrencyError()

    if not voucher:
        raise VoucherNotFoundError()

    if voucher.status != "issued":
        raise ValueError(f"El bono tiene estado '{voucher.status}', debe estar 'emitido' para venderlo")

    # High value SARLAFT check
    if voucher.face_value >= HIGH_VALUE_THRESHOLD and not buyer_id_document:
        raise VoucherHighValueRequiresIdError()

    now = datetime.now(timezone.utc)
    voucher.status = "sold"
    voucher.sold_at = now
    voucher.purchase_sale_id = sale_id
    voucher.buyer_name = buyer_name
    voucher.buyer_customer_id = buyer_customer_id
    voucher.buyer_id_document = buyer_id_document
    voucher.updated_by = cashier_id
    voucher.version += 1

    _log_transaction(
        voucher=voucher,
        transaction_type="sold",
        amount_change=voucher.face_value,
        performed_by=cashier_id,
        sale_id=sale_id,
        notes=f"Vendido a {buyer_name or 'cliente anónimo'}",
        idempotency_key=idempotency_key,
    )

    return {
        "voucher_id": str(voucher.id),
        "code": voucher.code,
        "face_value": float(voucher.face_value),
        "expires_at": voucher.expires_at.isoformat(),
        "accounting": {
            "debit_puc": "1105",  # Caja
            "credit_puc": "2910",  # Bonos por redimir (pasivo)
            "amount": float(voucher.face_value),
            "description": f"Venta bono {voucher.code}",
        },
    }


# ── Voucher Validation (pre-checkout) ────────────────────────────


def validate_voucher(tenant_id: str, code: str) -> dict:
    """Validate a voucher before applying it to a sale. Read-only."""
    code = code.upper().strip()

    if not verify_voucher_code_format(code, str(tenant_id)):
        raise VoucherInvalidCodeError()

    voucher = Voucher.query.filter_by(code=code, tenant_id=tenant_id).first()
    if not voucher:
        raise VoucherNotFoundError()

    now = datetime.now(timezone.utc)
    errors = []

    if voucher.status == "redeemed":
        errors.append("Este bono ya fue totalmente redimido")
    elif voucher.status == "expired":
        errors.append("Este bono ha expirado")
    elif voucher.status == "cancelled":
        errors.append("Este bono fue cancelado")
    elif voucher.status == "issued":
        errors.append("Este bono no ha sido vendido aún")
    elif voucher.expires_at and now > voucher.expires_at:
        errors.append("Este bono ha expirado")

    return {
        "valid": len(errors) == 0,
        "code": voucher.code,
        "face_value": float(voucher.face_value),
        "remaining_balance": float(voucher.remaining_balance),
        "status": voucher.status,
        "expires_at": voucher.expires_at.isoformat() if voucher.expires_at else None,
        "errors": errors,
    }


# ── Voucher Redemption (POS) ─────────────────────────────────────


def redeem_voucher(
    tenant_id: str,
    code: str,
    sale_id: str,
    amount: float,
    cashier_id: str,
    idempotency_key: str,
    payment_id: str = None,
) -> dict:
    """
    Redeem a voucher (partially or fully) within a POS transaction.
    Called inside the checkout atomic transaction.
    Uses SELECT FOR UPDATE NOWAIT to prevent double redemption.
    """
    code = code.upper().strip()
    amount_dec = Decimal(str(amount)).quantize(TWO_PLACES)

    # HMAC verification before DB query
    if not verify_voucher_code_format(code, str(tenant_id)):
        raise VoucherInvalidCodeError()

    # Lock the voucher row — NOWAIT returns immediately if locked
    try:
        voucher = Voucher.query.filter_by(code=code, tenant_id=tenant_id).with_for_update(nowait=True).first()
    except OperationalError:
        raise VoucherConcurrencyError()

    if not voucher:
        raise VoucherNotFoundError()

    # State validations
    if voucher.status in ("redeemed",):
        raise VoucherAlreadyRedeemedError()
    if voucher.status == "expired":
        raise VoucherExpiredError()
    if voucher.status == "cancelled":
        raise VoucherCancelledError()
    if voucher.status == "issued":
        raise VoucherNotSoldError()

    # Check expiry
    now = datetime.now(timezone.utc)
    if voucher.expires_at and now > voucher.expires_at:
        voucher.status = "expired"
        raise VoucherExpiredError()

    # Balance check
    if amount_dec > voucher.remaining_balance:
        raise VoucherInsufficientBalanceError(
            f"Saldo del bono: ${float(voucher.remaining_balance):,.0f}, " f"monto solicitado: ${float(amount_dec):,.0f}"
        )
    if amount_dec <= 0:
        raise ValueError("El monto a redimir debe ser mayor a 0")

    # Update voucher
    voucher.remaining_balance -= amount_dec

    if voucher.remaining_balance == 0:
        voucher.status = "redeemed"
        voucher.fully_redeemed_at = now
    else:
        voucher.status = "partially_redeemed"

    voucher.updated_by = cashier_id
    voucher.version += 1

    _log_transaction(
        voucher=voucher,
        transaction_type="redeemed",
        amount_change=-amount_dec,
        performed_by=cashier_id,
        sale_id=sale_id,
        payment_id=payment_id,
        notes=f"Redimido ${float(amount_dec):,.0f} en venta",
        idempotency_key=idempotency_key,
    )

    return {
        "voucher_id": str(voucher.id),
        "code": voucher.code,
        "amount_applied": float(amount_dec),
        "remaining_balance": float(voucher.remaining_balance),
        "status": voucher.status,
        "accounting": {
            "debit_puc": "2910",  # Bonos por redimir (libera pasivo)
            "credit_puc": "4135",  # Ingresos ventas
            "amount": float(amount_dec),
            "description": f"Redención bono {voucher.code}",
        },
    }


# ── Voucher Expiration ───────────────────────────────────────────


def expire_due_vouchers(tenant_id: str = None) -> dict:
    """
    Mark sold/partially_redeemed vouchers as expired when past expires_at.
    If tenant_id is None, processes all tenants.
    Returns accounting data for each expired voucher (quarantine step).
    """
    now = datetime.now(timezone.utc)
    q = Voucher.query.filter(
        Voucher.status.in_(["sold", "partially_redeemed"]),
        Voucher.expires_at < now,
    )
    if tenant_id:
        q = q.filter(Voucher.tenant_id == tenant_id)

    vouchers = q.all()
    results = []

    for voucher in vouchers:
        balance = voucher.remaining_balance
        voucher.status = "expired"
        voucher.version += 1

        _log_transaction(
            voucher=voucher,
            transaction_type="expired",
            amount_change=-balance,
            performed_by="system",
            notes=f"Bono expirado, saldo ${float(balance):,.0f} a cuarentena",
        )

        results.append(
            {
                "voucher_id": str(voucher.id),
                "tenant_id": str(voucher.tenant_id),
                "code": voucher.code,
                "expired_balance": float(balance),
                "accounting": {
                    "debit_puc": "2910",  # Bonos por redimir
                    "credit_puc": "2910",  # Bonos en cuarentena (sub-cuenta 02)
                    "amount": float(balance),
                    "description": f"Bono {voucher.code} expirado → cuarentena",
                },
            }
        )

    if results:
        db.session.commit()

    return {"expired_count": len(results), "vouchers": results}


# ── Voucher Cancellation ─────────────────────────────────────────


def cancel_voucher(
    tenant_id: str,
    voucher_id: str,
    cancelled_by: str,
    reason: str,
) -> dict:
    """Cancel an issued (unsold) voucher."""
    voucher = Voucher.query.filter_by(id=voucher_id, tenant_id=tenant_id).with_for_update().first()

    if not voucher:
        raise VoucherNotFoundError()
    if voucher.status not in ("issued",):
        raise ValueError("Solo se pueden cancelar bonos que no han sido vendidos")

    voucher.status = "cancelled"
    voucher.cancelled_at = datetime.now(timezone.utc)
    voucher.remaining_balance = Decimal("0")
    voucher.updated_by = cancelled_by
    voucher.version += 1

    _log_transaction(
        voucher=voucher,
        transaction_type="cancelled",
        amount_change=-voucher.face_value,
        performed_by=cancelled_by,
        notes=f"Cancelado: {reason}",
    )

    # Decrement issued_count on the type
    vt = VoucherType.query.get(voucher.voucher_type_id)
    if vt and vt.issued_count > 0:
        vt.issued_count -= 1

    db.session.commit()
    return _voucher_to_dict(voucher)


# ── Refund → New Voucher ─────────────────────────────────────────


def issue_refund_voucher(
    tenant_id: str,
    original_voucher_id: str,
    refund_amount: float,
    created_by: str,
) -> dict:
    """Issue a new voucher as refund for a return paid with voucher."""
    original = Voucher.query.filter_by(id=original_voucher_id, tenant_id=tenant_id).first()
    if not original:
        raise VoucherNotFoundError("Bono original no encontrado")

    # Create new voucher with same type
    result = emit_voucher(
        tenant_id=tenant_id,
        type_id=str(original.voucher_type_id),
        created_by=created_by,
        idempotency_key=f"refund-{original_voucher_id}-{uuid.uuid4().hex[:8]}",
    )

    # If refund amount differs from face value, adjust balance
    new_voucher = Voucher.query.get(result["id"])
    if new_voucher and Decimal(str(refund_amount)) != new_voucher.face_value:
        # For partial refund, set remaining_balance to refund amount
        new_voucher.remaining_balance = Decimal(str(refund_amount)).quantize(TWO_PLACES)

    db.session.commit()
    return _voucher_to_dict(new_voucher)


# ── Print Tracking ───────────────────────────────────────────────


def record_print(tenant_id: str, voucher_id: str, printed_by: str) -> dict:
    """Record a print event for a voucher. Max 3 reprints."""
    voucher = Voucher.query.filter_by(id=voucher_id, tenant_id=tenant_id).first()
    if not voucher:
        raise VoucherNotFoundError()

    if voucher.status in ("redeemed", "cancelled"):
        raise VoucherPrintLimitError("No se puede imprimir un bono ya redimido o cancelado")

    if voucher.print_count >= MAX_PRINT_COUNT:
        raise VoucherPrintLimitError()

    voucher.print_count += 1
    voucher.last_printed_at = datetime.now(timezone.utc)
    db.session.commit()

    return _voucher_to_dict(voucher)


# ── Send Voucher Email ───────────────────────────────────────────


def send_voucher_email(tenant_id: str, voucher_id: str, to_email: str, sent_by: str) -> dict:
    """Send voucher card via email using the tenant's SMTP config."""
    from flask import render_template

    from app.core.email_service import send_email
    from app.modules.auth_rbac.models import Tenant
    from app.modules.vouchers.print_service import build_voucher_print_data

    voucher = Voucher.query.filter_by(id=voucher_id, tenant_id=tenant_id).first()
    if not voucher:
        raise VoucherNotFoundError()

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        raise ValueError("Tenant no encontrado")

    if not tenant.smtp_host:
        raise ValueError("El negocio no tiene configurado el correo SMTP. Configure en Mi Negocio > SMTP.")

    vt = VoucherType.query.get(voucher.voucher_type_id)
    t_dict = {
        "name": tenant.name,
        "trade_name": tenant.trade_name or tenant.name,
        "tax_id": tenant.tax_id or "",
        "address": tenant.address or "",
        "phone": tenant.phone or "",
        "logo_url": tenant.logo_url or "",
    }
    color = vt.color_hex if vt and vt.color_hex else "#1E3A8A"
    print_data = build_voucher_print_data(_voucher_to_dict(voucher), t_dict, color_hex=color)

    issuer_name = tenant.trade_name or tenant.name
    subject = f"Bono de Descuento {print_data['face_value_formatted']} — {issuer_name}"
    body_html = render_template("vouchers/voucher_email.html", voucher=print_data)

    send_email(
        smtp_host=tenant.smtp_host,
        smtp_port=tenant.smtp_port or 587,
        smtp_user=tenant.smtp_user,
        smtp_password=tenant.smtp_password,
        from_email=tenant.smtp_from_email or tenant.smtp_user,
        to_email=to_email,
        subject=subject,
        body_html=body_html,
    )

    _log_transaction(
        voucher=voucher,
        transaction_type="adjusted",
        amount_change=Decimal("0"),
        performed_by=sent_by,
        notes=f"Bono enviado por email a {to_email}",
    )
    db.session.commit()

    return {"sent_to": to_email, "voucher_code": voucher.code}


# ── Queries ──────────────────────────────────────────────────────


def get_voucher(tenant_id: str, voucher_id: str) -> Optional[dict]:
    """Get a voucher by ID."""
    v = Voucher.query.filter_by(id=voucher_id, tenant_id=tenant_id).first()
    return _voucher_to_dict(v) if v else None


def get_voucher_by_code(tenant_id: str, code: str) -> Optional[dict]:
    """Get a voucher by code."""
    code = code.upper().strip()
    v = Voucher.query.filter_by(code=code, tenant_id=tenant_id).first()
    return _voucher_to_dict(v) if v else None


def list_vouchers(
    tenant_id: str,
    page: int = 1,
    per_page: int = 20,
    status: str = None,
    type_id: str = None,
) -> dict:
    """List vouchers with filters."""
    q = Voucher.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter(Voucher.status == status)
    if type_id:
        q = q.filter(Voucher.voucher_type_id == type_id)

    total = q.count()
    vouchers = q.order_by(Voucher.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "data": [_voucher_to_dict(v) for v in vouchers],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "has_next": page * per_page < total,
        },
    }


def get_voucher_stats(tenant_id: str) -> dict:
    """Dashboard stats: counts and values by status."""
    stats = (
        db.session.query(
            Voucher.status,
            func.count(Voucher.id).label("count"),
            func.coalesce(func.sum(Voucher.face_value), 0).label("total_face_value"),
            func.coalesce(func.sum(Voucher.remaining_balance), 0).label("total_remaining"),
        )
        .filter(Voucher.tenant_id == tenant_id)
        .group_by(Voucher.status)
        .all()
    )

    result = {
        "by_status": {},
        "total_issued_value": 0,
        "total_in_circulation": 0,
    }

    for row in stats:
        result["by_status"][row.status] = {
            "count": row.count,
            "total_face_value": float(row.total_face_value),
            "total_remaining": float(row.total_remaining),
        }
        if row.status in ("sold", "partially_redeemed"):
            result["total_in_circulation"] += float(row.total_remaining)
        result["total_issued_value"] += float(row.total_face_value)

    return result


def get_voucher_history(tenant_id: str, voucher_id: str) -> list:
    """Get full transaction history for a voucher."""
    txns = (
        VoucherTransaction.query.filter_by(voucher_id=voucher_id, tenant_id=tenant_id)
        .order_by(VoucherTransaction.occurred_at.desc())
        .all()
    )

    return [_transaction_to_dict(t) for t in txns]


# ── Internal Helpers ─────────────────────────────────────────────


def _log_transaction(
    voucher: Voucher,
    transaction_type: str,
    amount_change: Decimal,
    performed_by: str,
    sale_id: str = None,
    payment_id: str = None,
    journal_entry_id: str = None,
    notes: str = None,
    idempotency_key: str = None,
) -> VoucherTransaction:
    """Create an immutable transaction log entry."""
    if amount_change < 0:
        balance_before = voucher.remaining_balance + abs(amount_change)
    else:
        balance_before = voucher.remaining_balance - amount_change

    ip_address = None
    try:
        ip_address = flask_request.remote_addr
    except RuntimeError:
        pass  # Outside request context (e.g., Celery task)

    txn = VoucherTransaction(
        tenant_id=voucher.tenant_id,
        voucher_id=voucher.id,
        transaction_type=transaction_type,
        amount_change=amount_change,
        balance_before=max(balance_before, Decimal("0")),
        balance_after=voucher.remaining_balance,
        sale_id=sale_id,
        payment_id=payment_id,
        journal_entry_id=journal_entry_id,
        performed_by=performed_by,
        notes=notes,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        ip_address=ip_address,
    )
    db.session.add(txn)
    return txn


# ── Serializers ──────────────────────────────────────────────────


def _voucher_type_to_dict(vt: VoucherType) -> dict:
    return {
        "id": str(vt.id),
        "tenant_id": str(vt.tenant_id),
        "name": vt.name,
        "face_value": float(vt.face_value),
        "validity_days": vt.validity_days,
        "max_issuable": vt.max_issuable,
        "issued_count": vt.issued_count,
        "status": vt.status,
        "color_hex": vt.color_hex,
        "design_template": vt.design_template,
        "notes": vt.notes,
        "can_issue": vt.can_issue,
        "created_at": vt.created_at.isoformat(),
    }


def _voucher_to_dict(v: Voucher) -> dict:
    return {
        "id": str(v.id),
        "tenant_id": str(v.tenant_id),
        "voucher_type_id": str(v.voucher_type_id),
        "code": v.code,
        "status": v.status,
        "face_value": float(v.face_value),
        "remaining_balance": float(v.remaining_balance),
        "issued_at": v.issued_at.isoformat() if v.issued_at else None,
        "sold_at": v.sold_at.isoformat() if v.sold_at else None,
        "expires_at": v.expires_at.isoformat() if v.expires_at else None,
        "fully_redeemed_at": v.fully_redeemed_at.isoformat() if v.fully_redeemed_at else None,
        "buyer_name": v.buyer_name,
        "print_count": v.print_count,
        "is_redeemable": v.is_redeemable,
        "is_expired": v.is_expired,
        "created_at": v.created_at.isoformat(),
    }


def _transaction_to_dict(t: VoucherTransaction) -> dict:
    return {
        "id": str(t.id),
        "transaction_type": t.transaction_type,
        "amount_change": float(t.amount_change),
        "balance_before": float(t.balance_before),
        "balance_after": float(t.balance_after),
        "sale_id": str(t.sale_id) if t.sale_id else None,
        "performed_by": str(t.performed_by),
        "notes": t.notes,
        "occurred_at": t.occurred_at.isoformat(),
    }
