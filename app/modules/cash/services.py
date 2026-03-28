"""Cash services — Receipts, Disbursements, Transfers with auto-posting."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.modules.cash.models import (
    CashReceipt, CashDisbursement, CashTransfer, CashCountDetail,
)

TWO_PLACES = Decimal("0.01")


# ── Number generators ────────────────────────────────────────────

def _next_number(model, prefix, tenant_id):
    year = datetime.now(timezone.utc).year
    full_prefix = f"{prefix}-{year}-"
    col = getattr(model, list(model.__table__.columns.keys())[3])  # number column
    # Use explicit column reference
    if hasattr(model, "receipt_number"):
        col = model.receipt_number
    elif hasattr(model, "disbursement_number"):
        col = model.disbursement_number
    elif hasattr(model, "transfer_number"):
        col = model.transfer_number
    last = (
        db.session.query(func.max(col))
        .filter(model.tenant_id == tenant_id, col.like(f"{full_prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{full_prefix}{seq:06d}"


# ── Accounting entry mapping by source/destination type ──────────

RECEIPT_ACCOUNTS = {
    "customer_payment": "1305",  # CR Clientes
    "other_income": "4210",      # CR Ingresos no operacionales
    "loan": "2335",              # CR Costos y gastos por pagar (prestamo)
    "partner_capital": "3105",   # CR Capital social
}

DISBURSEMENT_ACCOUNTS = {
    "supplier_payment": "2205",  # DB Proveedores nacionales
    "petty_cash": "1705",        # DB Caja menor
    "bank_transfer": "1110",     # DB Bancos
}


# ── Cash Receipt Services ────────────────────────────────────────

def create_cash_receipt(
    tenant_id: str, created_by: str, source_type: str,
    concept: str, amount: float, payment_method: str = "cash",
    source_id: str = None, source_name: str = None,
    reference: str = None, notes: str = None,
    cash_session_id: str = None,
) -> dict:
    """Create a cash receipt and generate the accounting entry."""
    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    if amt <= 0:
        raise ValueError("El monto debe ser mayor a 0")

    receipt = CashReceipt(
        tenant_id=tenant_id, created_by=created_by,
        receipt_number=_next_number(CashReceipt, "RC", tenant_id),
        source_type=source_type, source_id=source_id,
        source_name=source_name, concept=concept,
        amount=amt, payment_method=payment_method,
        reference=reference, notes=notes,
        cash_session_id=cash_session_id,
    )
    db.session.add(receipt)
    db.session.flush()

    # Accounting: DB 1105 Caja (o 1110 Bancos) | CR {cuenta según tipo}
    from app.modules.accounting.services import create_journal_entry
    debit_account = "1105" if payment_method == "cash" else "1110"
    credit_account = RECEIPT_ACCOUNTS.get(source_type, "4210")

    create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="CASH_RECEIPT",
        description=f"Recibo {receipt.receipt_number}: {concept}",
        lines=[
            {"puc_code": debit_account, "debit": float(amt), "credit": 0,
             "description": f"Ingreso - {concept}"},
            {"puc_code": credit_account, "debit": 0, "credit": float(amt),
             "description": source_name or concept},
        ],
        source_document_type="cash_receipt", source_document_id=str(receipt.id),
    )

    db.session.commit()
    return _receipt_to_dict(receipt)


def get_cash_receipts(tenant_id: str, date_from: str = None, date_to: str = None) -> list:
    q = CashReceipt.query.filter_by(tenant_id=tenant_id)
    if date_from:
        q = q.filter(CashReceipt.receipt_date >= date_from)
    if date_to:
        q = q.filter(CashReceipt.receipt_date <= date_to)
    return [_receipt_to_dict(r) for r in q.order_by(CashReceipt.created_at.desc()).all()]


def void_cash_receipt(tenant_id: str, receipt_id: str, user_id: str) -> dict:
    receipt = CashReceipt.query.filter_by(id=receipt_id, tenant_id=tenant_id).first()
    if not receipt:
        raise ValueError("Recibo no encontrado")
    if receipt.status == "voided":
        raise ValueError("El recibo ya fue anulado")

    receipt.status = "voided"
    receipt.voided_at = datetime.now(timezone.utc)
    receipt.voided_by = user_id

    from app.modules.accounting.services import create_journal_entry
    debit_account = "1105" if receipt.payment_method == "cash" else "1110"
    credit_account = RECEIPT_ACCOUNTS.get(receipt.source_type, "4210")

    create_journal_entry(
        tenant_id=tenant_id, created_by=user_id,
        entry_type="REVERSAL",
        description=f"Anulación recibo {receipt.receipt_number}",
        lines=[
            {"puc_code": credit_account, "debit": float(receipt.amount), "credit": 0,
             "description": "Reversa ingreso"},
            {"puc_code": debit_account, "debit": 0, "credit": float(receipt.amount),
             "description": "Reversa caja/banco"},
        ],
        source_document_type="cash_receipt_void", source_document_id=str(receipt.id),
    )

    db.session.commit()
    return _receipt_to_dict(receipt)


# ── Cash Disbursement Services ───────────────────────────────────

def create_cash_disbursement(
    tenant_id: str, created_by: str, destination_type: str,
    concept: str, amount: float, payment_method: str = "cash",
    puc_code: str = None, destination_id: str = None,
    destination_name: str = None, reference: str = None,
    notes: str = None, cash_session_id: str = None,
) -> dict:
    """Create a cash disbursement and generate the accounting entry."""
    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    if amt <= 0:
        raise ValueError("El monto debe ser mayor a 0")

    disb = CashDisbursement(
        tenant_id=tenant_id, created_by=created_by,
        disbursement_number=_next_number(CashDisbursement, "CE", tenant_id),
        destination_type=destination_type, destination_id=destination_id,
        destination_name=destination_name, concept=concept,
        amount=amt, payment_method=payment_method,
        puc_code=puc_code, reference=reference, notes=notes,
        cash_session_id=cash_session_id,
    )
    db.session.add(disb)
    db.session.flush()

    from app.modules.accounting.services import create_journal_entry
    credit_account = "1105" if payment_method == "cash" else "1110"

    # Determine debit account
    if destination_type == "expense" and puc_code:
        debit_account = puc_code  # User selects expense PUC (5105, 5135, 5160, etc.)
    elif destination_type in DISBURSEMENT_ACCOUNTS:
        debit_account = DISBURSEMENT_ACCOUNTS[destination_type]
    else:
        debit_account = "5195"  # Default: gastos diversos

    create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="CASH_DISBURSEMENT",
        description=f"Egreso {disb.disbursement_number}: {concept}",
        lines=[
            {"puc_code": debit_account, "debit": float(amt), "credit": 0,
             "description": concept},
            {"puc_code": credit_account, "debit": 0, "credit": float(amt),
             "description": f"Egreso - {disb.disbursement_number}"},
        ],
        source_document_type="cash_disbursement", source_document_id=str(disb.id),
    )

    db.session.commit()
    return _disbursement_to_dict(disb)


def get_cash_disbursements(tenant_id: str, date_from: str = None, date_to: str = None) -> list:
    q = CashDisbursement.query.filter_by(tenant_id=tenant_id)
    if date_from:
        q = q.filter(CashDisbursement.disbursement_date >= date_from)
    if date_to:
        q = q.filter(CashDisbursement.disbursement_date <= date_to)
    return [_disbursement_to_dict(d) for d in q.order_by(CashDisbursement.created_at.desc()).all()]


def void_cash_disbursement(tenant_id: str, disb_id: str, user_id: str) -> dict:
    disb = CashDisbursement.query.filter_by(id=disb_id, tenant_id=tenant_id).first()
    if not disb:
        raise ValueError("Egreso no encontrado")
    if disb.status == "voided":
        raise ValueError("El egreso ya fue anulado")

    disb.status = "voided"
    disb.voided_at = datetime.now(timezone.utc)
    disb.voided_by = user_id

    from app.modules.accounting.services import create_journal_entry
    credit_account = "1105" if disb.payment_method == "cash" else "1110"
    if disb.destination_type == "expense" and disb.puc_code:
        debit_account = disb.puc_code
    elif disb.destination_type in DISBURSEMENT_ACCOUNTS:
        debit_account = DISBURSEMENT_ACCOUNTS[disb.destination_type]
    else:
        debit_account = "5195"

    create_journal_entry(
        tenant_id=tenant_id, created_by=user_id,
        entry_type="REVERSAL",
        description=f"Anulación egreso {disb.disbursement_number}",
        lines=[
            {"puc_code": credit_account, "debit": float(disb.amount), "credit": 0,
             "description": "Reversa salida"},
            {"puc_code": debit_account, "debit": 0, "credit": float(disb.amount),
             "description": "Reversa gasto/pago"},
        ],
        source_document_type="cash_disbursement_void", source_document_id=str(disb.id),
    )

    db.session.commit()
    return _disbursement_to_dict(disb)


# ── Cash Transfer Services ───────────────────────────────────────

def create_cash_transfer(
    tenant_id: str, created_by: str,
    from_account_puc: str, to_account_puc: str,
    amount: float, reference: str = None, notes: str = None,
) -> dict:
    """Transfer between cash/bank accounts."""
    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    if amt <= 0:
        raise ValueError("El monto debe ser mayor a 0")
    if from_account_puc == to_account_puc:
        raise ValueError("Las cuentas origen y destino deben ser diferentes")

    transfer = CashTransfer(
        tenant_id=tenant_id, created_by=created_by,
        transfer_number=_next_number(CashTransfer, "TR", tenant_id),
        from_account_puc=from_account_puc, to_account_puc=to_account_puc,
        amount=amt, reference=reference, notes=notes,
    )
    db.session.add(transfer)
    db.session.flush()

    from app.modules.accounting.services import create_journal_entry
    # Account names for description
    NAMES = {"1105": "Caja", "1110": "Bancos", "1115": "Cuentas de ahorro", "1705": "Caja menor"}
    from_name = NAMES.get(from_account_puc, from_account_puc)
    to_name = NAMES.get(to_account_puc, to_account_puc)

    create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="TRANSFER",
        description=f"Traslado {from_name} → {to_name} - {transfer.transfer_number}",
        lines=[
            {"puc_code": to_account_puc, "debit": float(amt), "credit": 0,
             "description": f"Ingreso desde {from_name}"},
            {"puc_code": from_account_puc, "debit": 0, "credit": float(amt),
             "description": f"Traslado a {to_name}"},
        ],
        source_document_type="cash_transfer", source_document_id=str(transfer.id),
    )

    db.session.commit()
    return _transfer_to_dict(transfer)


def get_cash_transfers(tenant_id: str) -> list:
    transfers = CashTransfer.query.filter_by(
        tenant_id=tenant_id
    ).order_by(CashTransfer.created_at.desc()).all()
    return [_transfer_to_dict(t) for t in transfers]


# ── Cash Count (Arqueo) ──────────────────────────────────────────

def save_cash_count(cash_session_id: str, denominations: list) -> list:
    """Save denomination count details for a cash session close.
    denominations: [{"denomination": 50000, "quantity": 3}, ...]
    """
    # Remove existing counts for this session
    CashCountDetail.query.filter_by(cash_session_id=cash_session_id).delete()

    details = []
    for d in denominations:
        denom = int(d["denomination"])
        qty = int(d["quantity"])
        detail = CashCountDetail(
            cash_session_id=cash_session_id,
            denomination=denom,
            quantity=qty,
            subtotal=Decimal(str(denom * qty)),
        )
        db.session.add(detail)
        details.append(detail)

    db.session.flush()
    return [{
        "denomination": d.denomination,
        "quantity": d.quantity,
        "subtotal": float(d.subtotal),
    } for d in details]


# ── Serializers ──────────────────────────────────────────────────

SOURCE_TYPE_LABELS = {
    "customer_payment": "Pago de cliente",
    "other_income": "Otro ingreso",
    "loan": "Préstamo",
    "partner_capital": "Aporte socio",
}

DEST_TYPE_LABELS = {
    "supplier_payment": "Pago proveedor",
    "expense": "Gasto",
    "petty_cash": "Caja menor",
    "bank_transfer": "Traslado a banco",
    "other": "Otro",
}

METHOD_LABELS = {
    "cash": "Efectivo",
    "transfer": "Transferencia",
    "check": "Cheque",
    "nequi": "Nequi",
    "daviplata": "Daviplata",
}


def _receipt_to_dict(r: CashReceipt) -> dict:
    return {
        "id": str(r.id),
        "receipt_number": r.receipt_number,
        "receipt_date": r.receipt_date.isoformat(),
        "source_type": r.source_type,
        "source_type_label": SOURCE_TYPE_LABELS.get(r.source_type, r.source_type),
        "source_name": r.source_name,
        "concept": r.concept,
        "amount": float(r.amount),
        "payment_method": r.payment_method,
        "method_label": METHOD_LABELS.get(r.payment_method, r.payment_method),
        "reference": r.reference,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
    }


def _disbursement_to_dict(d: CashDisbursement) -> dict:
    return {
        "id": str(d.id),
        "disbursement_number": d.disbursement_number,
        "disbursement_date": d.disbursement_date.isoformat(),
        "destination_type": d.destination_type,
        "destination_type_label": DEST_TYPE_LABELS.get(d.destination_type, d.destination_type),
        "destination_name": d.destination_name,
        "concept": d.concept,
        "amount": float(d.amount),
        "payment_method": d.payment_method,
        "method_label": METHOD_LABELS.get(d.payment_method, d.payment_method),
        "puc_code": d.puc_code,
        "reference": d.reference,
        "status": d.status,
        "created_at": d.created_at.isoformat(),
    }


def _transfer_to_dict(t: CashTransfer) -> dict:
    NAMES = {"1105": "Caja", "1110": "Bancos", "1115": "Cuentas de ahorro", "1705": "Caja menor"}
    return {
        "id": str(t.id),
        "transfer_number": t.transfer_number,
        "transfer_date": t.transfer_date.isoformat(),
        "from_account_puc": t.from_account_puc,
        "from_account_name": NAMES.get(t.from_account_puc, t.from_account_puc),
        "to_account_puc": t.to_account_puc,
        "to_account_name": NAMES.get(t.to_account_puc, t.to_account_puc),
        "amount": float(t.amount),
        "reference": t.reference,
        "status": t.status,
        "created_at": t.created_at.isoformat(),
    }
