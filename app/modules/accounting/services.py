"""Accounting services — PUC, journal entries, auto-posting, periods."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.modules.accounting.models import (
    AccountingPeriod, ChartOfAccount, JournalEntry, JournalLine,
    Expense, WithholdingConfig,
)


TWO_PLACES = Decimal("0.01")


# ── Period Services ───────────────────────────────────────────────

def get_or_create_period(tenant_id: str, date: datetime = None) -> AccountingPeriod:
    """Get or create the accounting period for a given date."""
    if not date:
        date = datetime.now(timezone.utc)

    period = AccountingPeriod.query.filter_by(
        tenant_id=tenant_id, year=date.year, month=date.month
    ).first()

    if not period:
        period = AccountingPeriod(
            tenant_id=tenant_id, year=date.year, month=date.month
        )
        db.session.add(period)
        db.session.flush()

    return period


def close_period(tenant_id: str, year: int, month: int, user_id: str) -> dict:
    """Close an accounting period. No more entries allowed after close."""
    period = AccountingPeriod.query.filter_by(
        tenant_id=tenant_id, year=year, month=month
    ).first()
    if not period:
        raise ValueError(f"Periodo {year}-{month:02d} no encontrado")
    if period.status != "open":
        raise ValueError(f"Periodo {year}-{month:02d} ya está {period.status}")

    # Verify balance
    balance = get_trial_balance(tenant_id, year, month)
    if abs(balance["total_debit"] - balance["total_credit"]) > 0.01:
        raise ValueError("No se puede cerrar: débitos y créditos no cuadran")

    period.status = "closed"
    period.closed_at = datetime.now(timezone.utc)
    period.closed_by = user_id
    db.session.commit()

    return _period_to_dict(period)


# ── Journal Entry Services ────────────────────────────────────────

def create_journal_entry(
    tenant_id: str, created_by: str, entry_type: str,
    description: str, lines: list,
    source_document_type: str = None, source_document_id: str = None,
    entry_date: datetime = None,
) -> dict:
    """
    Create a balanced journal entry.
    lines: [{"puc_code": str, "debit": float, "credit": float, "description": str}]
    """
    if not entry_date:
        entry_date = datetime.now(timezone.utc)

    period = get_or_create_period(tenant_id, entry_date)
    if period.status == "locked":
        raise ValueError(f"Periodo {period.year}-{period.month:02d} está bloqueado")
    # Block entries in closed periods (except CLOSING and REVERSAL which are part of close/reopen flow)
    if period.status == "closed" and entry_type not in ("CLOSING", "REVERSAL"):
        raise ValueError(f"Periodo {period.year}-{period.month:02d} está cerrado. Reabra el periodo para registrar movimientos.")

    # Validate double-entry
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    entry = JournalEntry(
        tenant_id=tenant_id, period_id=period.id, created_by=created_by,
        entry_date=entry_date, entry_type=entry_type, description=description,
        source_document_type=source_document_type,
        source_document_id=source_document_id,
    )

    entry_lines = []
    for line_data in lines:
        # Support both puc_code and account_id
        account = None
        if line_data.get("account_id"):
            account = ChartOfAccount.query.filter_by(
                id=line_data["account_id"], tenant_id=tenant_id
            ).first()
        elif line_data.get("puc_code"):
            account = ChartOfAccount.query.filter_by(
                tenant_id=tenant_id, puc_code=line_data["puc_code"]
            ).first()
        if not account:
            ref = line_data.get("puc_code") or line_data.get("account_id", "?")
            raise ValueError(f"Cuenta {ref} no encontrada")

        debit = Decimal(str(line_data.get("debit", 0))).quantize(TWO_PLACES)
        credit = Decimal(str(line_data.get("credit", 0))).quantize(TWO_PLACES)

        if debit == 0 and credit == 0:
            raise ValueError("Línea debe tener débito o crédito mayor a 0")
        if debit > 0 and credit > 0:
            raise ValueError("Línea no puede tener débito Y crédito al mismo tiempo")

        entry_lines.append(JournalLine(
            tenant_id=tenant_id,
            account_id=account.id,
            debit_amount=debit, credit_amount=credit,
            description=line_data.get("description", ""),
        ))
        total_debit += debit
        total_credit += credit

    if total_debit != total_credit:
        raise ValueError(
            f"Asiento desbalanceado: débitos={total_debit}, créditos={total_credit}"
        )

    entry.total_debit = total_debit
    entry.total_credit = total_credit
    entry.lines = entry_lines

    db.session.add(entry)
    db.session.flush()  # Let caller control commit (checkout, receive_po, etc.)
    return _entry_to_dict(entry)


# ── Auto-posting: Sale ────────────────────────────────────────────

def post_sale_entry(
    tenant_id: str, created_by: str, sale_id: str,
    subtotal: float, tax_amount: float, total_amount: float,
    cost_total: float, payment_method: str = "cash",
    fiscal_regime: str = "simplified",
) -> dict:
    """
    Auto-generate journal entries for a sale.
    Entry 1: Revenue + IVA
    Entry 2: Cost of goods sold
    """
    entries = []
    sub = Decimal(str(subtotal)).quantize(TWO_PLACES)
    tax = Decimal(str(tax_amount)).quantize(TWO_PLACES)
    total = Decimal(str(total_amount)).quantize(TWO_PLACES)
    cost = Decimal(str(cost_total)).quantize(TWO_PLACES)

    # Determine debit account: 1305 Clientes for credit, 1105/1110 for cash
    if payment_method == "credit":
        cash_account = "1305"
    elif payment_method == "cash":
        cash_account = "1105"
    else:
        cash_account = "1110"

    # Entry 1: Revenue
    debit_desc = "Cuenta por cobrar cliente" if payment_method == "credit" else "Cobro venta"
    revenue_lines = [
        {"puc_code": cash_account, "debit": float(total), "credit": 0,
         "description": debit_desc},
        {"puc_code": "4135", "debit": 0, "credit": float(sub),
         "description": "Ingreso por ventas"},
    ]

    # Add IVA line only if tenant is VAT responsible and tax > 0
    if tax > 0 and fiscal_regime != "simplified":
        revenue_lines.append({
            "puc_code": "2408", "debit": 0, "credit": float(tax),
            "description": "IVA generado 19%",
        })
    # Simplified regime: tax should be 0 (enforced at checkout).
    # No special handling needed — subtotal == total when tax == 0.

    entry1 = create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="SALE", description=f"Venta registrada",
        lines=revenue_lines,
        source_document_type="sale", source_document_id=sale_id,
    )
    entries.append(entry1)

    # Entry 2: Cost of goods sold
    if cost > 0:
        cost_lines = [
            {"puc_code": "6135", "debit": float(cost), "credit": 0,
             "description": "Costo de mercancía vendida"},
            {"puc_code": "1435", "debit": 0, "credit": float(cost),
             "description": "Salida de inventario"},
        ]
        entry2 = create_journal_entry(
            tenant_id=tenant_id, created_by=created_by,
            entry_type="SALE_COST", description=f"Costo de venta",
            lines=cost_lines,
            source_document_type="sale", source_document_id=sale_id,
        )
        entries.append(entry2)

    return entries


# ── Auto-posting: Sale Reversal ───────────────────────────────────

def post_sale_reversal(
    tenant_id: str, created_by: str, sale_id: str,
    subtotal: float, tax_amount: float, total_amount: float,
    cost_total: float, payment_method: str = "cash",
) -> dict:
    """Auto-generate reversal entries for a voided sale."""
    total = Decimal(str(total_amount)).quantize(TWO_PLACES)
    sub = Decimal(str(subtotal)).quantize(TWO_PLACES)
    tax = Decimal(str(tax_amount)).quantize(TWO_PLACES)
    cost = Decimal(str(cost_total)).quantize(TWO_PLACES)
    if payment_method == "credit":
        cash_account = "1305"  # CxC — reverse accounts receivable
    elif payment_method == "cash":
        cash_account = "1105"
    else:
        cash_account = "1110"

    # Reverse revenue using 4175 Devoluciones en ventas
    lines = [
        {"puc_code": "4175", "debit": float(sub), "credit": 0,
         "description": "Devolución en ventas"},
        {"puc_code": cash_account, "debit": 0, "credit": float(total),
         "description": "Devolución al cliente"},
    ]
    if tax > 0:
        lines.append({
            "puc_code": "2408", "debit": float(tax), "credit": 0,
            "description": "Reversa IVA generado",
        })

    entry1 = create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="REVERSAL", description="Anulación de venta",
        lines=lines,
        source_document_type="sale_void", source_document_id=sale_id,
    )

    entries = [entry1]

    # Reverse cost
    if cost > 0:
        cost_lines = [
            {"puc_code": "1435", "debit": float(cost), "credit": 0,
             "description": "Reingreso inventario por anulación"},
            {"puc_code": "6135", "debit": 0, "credit": float(cost),
             "description": "Reversa costo de venta"},
        ]
        entry2 = create_journal_entry(
            tenant_id=tenant_id, created_by=created_by,
            entry_type="REVERSAL", description="Reversa costo de venta",
            lines=cost_lines,
            source_document_type="sale_void", source_document_id=sale_id,
        )
        entries.append(entry2)

    return entries


# ── Auto-posting: Credit Note (partial return) ───────────────────

def post_sale_credit_note_entry(
    tenant_id: str, created_by: str, sale_id: str, credit_note_id: str,
    subtotal: float, tax_amount: float, total_amount: float,
    cost_total: float, payment_method: str = "cash",
) -> list:
    """Auto-generate entries for a credit note (partial return).
    Uses PUC 4175 (Devoluciones en ventas) instead of reversing 4135.
    """
    total = Decimal(str(total_amount)).quantize(TWO_PLACES)
    sub = Decimal(str(subtotal)).quantize(TWO_PLACES)
    tax = Decimal(str(tax_amount)).quantize(TWO_PLACES)
    cost = Decimal(str(cost_total)).quantize(TWO_PLACES)
    if payment_method == "credit":
        cash_account = "1305"
    elif payment_method == "cash":
        cash_account = "1105"
    else:
        cash_account = "1110"

    # Entry 1: Revenue reversal via 4175
    lines = [
        {"puc_code": "4175", "debit": float(sub), "credit": 0,
         "description": "Devolución parcial en ventas"},
        {"puc_code": cash_account, "debit": 0, "credit": float(total),
         "description": "Reembolso al cliente"},
    ]
    if tax > 0:
        lines.append({
            "puc_code": "2408", "debit": float(tax), "credit": 0,
            "description": "Reversa IVA por devolución",
        })

    entry1 = create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="REVERSAL", description="Nota crédito de venta",
        lines=lines,
        source_document_type="credit_note", source_document_id=credit_note_id,
    )
    entries = [entry1]

    # Entry 2: Cost reversal (inventory re-entry)
    if cost > 0:
        cost_lines = [
            {"puc_code": "1435", "debit": float(cost), "credit": 0,
             "description": "Reingreso inventario por devolución"},
            {"puc_code": "6135", "debit": 0, "credit": float(cost),
             "description": "Reversa costo de venta"},
        ]
        entry2 = create_journal_entry(
            tenant_id=tenant_id, created_by=created_by,
            entry_type="REVERSAL", description="Reversa costo - nota crédito",
            lines=cost_lines,
            source_document_type="credit_note", source_document_id=credit_note_id,
        )
        entries.append(entry2)

    return entries


# ── Trial Balance ─────────────────────────────────────────────────

def get_trial_balance(tenant_id: str, year: int = None, month: int = None) -> dict:
    """Generate trial balance for a period or all time."""
    q = (
        db.session.query(
            ChartOfAccount.puc_code,
            ChartOfAccount.name,
            ChartOfAccount.account_type,
            ChartOfAccount.normal_balance,
            func.coalesce(func.sum(JournalLine.debit_amount), 0).label("total_debit"),
            func.coalesce(func.sum(JournalLine.credit_amount), 0).label("total_credit"),
        )
        .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(ChartOfAccount.tenant_id == tenant_id)
    )

    if year and month:
        q = q.join(
            AccountingPeriod, JournalEntry.period_id == AccountingPeriod.id
        ).filter(
            AccountingPeriod.year == year, AccountingPeriod.month == month,
        )

    q = q.group_by(
        ChartOfAccount.puc_code, ChartOfAccount.name,
        ChartOfAccount.account_type, ChartOfAccount.normal_balance,
    ).order_by(ChartOfAccount.puc_code)

    rows = q.all()
    total_d = Decimal("0")
    total_c = Decimal("0")

    accounts = []
    for row in rows:
        d = Decimal(str(row.total_debit))
        c = Decimal(str(row.total_credit))
        balance = d - c if row.normal_balance == "debit" else c - d
        total_d += d
        total_c += c

        accounts.append({
            "puc_code": row.puc_code,
            "name": row.name,
            "account_type": row.account_type,
            "total_debit": float(d),
            "total_credit": float(c),
            "balance": float(balance),
        })

    return {
        "accounts": accounts,
        "total_debit": float(total_d),
        "total_credit": float(total_c),
        "is_balanced": abs(total_d - total_c) < Decimal("0.01"),
    }


# ── Expense Services ─────────────────────────────────────────────

def _next_expense_number(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"GTO-{year}-"
    last = (
        db.session.query(func.max(Expense.expense_number))
        .filter(Expense.tenant_id == tenant_id, Expense.expense_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def create_expense(
    tenant_id: str, created_by: str, puc_code: str,
    concept: str, amount: float, tax_amount: float = 0,
    payment_status: str = "paid", payment_method: str = "cash",
    supplier_id: str = None, receipt_reference: str = None,
    notes: str = None,
) -> dict:
    """Register an expense. Paid expenses debit cash; pending ones debit CxP."""
    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    tax = Decimal(str(tax_amount)).quantize(TWO_PLACES)
    total = amt + tax

    expense = Expense(
        tenant_id=tenant_id, created_by=created_by,
        expense_number=_next_expense_number(tenant_id),
        puc_code=puc_code, concept=concept,
        amount=amt, tax_amount=tax, total_amount=total,
        supplier_id=supplier_id, payment_status=payment_status,
        payment_method=payment_method,
        receipt_reference=receipt_reference, notes=notes,
    )
    if payment_status == "paid":
        expense.paid_at = datetime.now(timezone.utc)

    db.session.add(expense)
    db.session.flush()

    # Accounting entry
    lines = [
        {"puc_code": puc_code, "debit": float(amt), "credit": 0,
         "description": concept},
    ]
    if tax > 0:
        lines.append({"puc_code": "2408", "debit": float(tax), "credit": 0,
                       "description": "IVA descontable"})

    # Calculate withholdings (ReteFuente on expenses)
    withholdings = calculate_withholdings(tenant_id, amt, "purchases")
    total_withholdings = sum(Decimal(str(w["amount"])) for w in withholdings)
    net_payable = float(total - total_withholdings)

    for w in withholdings:
        lines.append({"puc_code": w["puc_code"], "debit": 0, "credit": w["amount"],
                       "description": f"{w['name']} ({w['rate']}%)"})

    if payment_status == "paid":
        cash_account = "1105" if payment_method == "cash" else "1110"
        lines.append({"puc_code": cash_account, "debit": 0, "credit": net_payable,
                       "description": f"Pago {expense.expense_number} (neto retenciones)"})
    else:
        lines.append({"puc_code": "2335", "debit": 0, "credit": net_payable,
                       "description": "Gasto causado por pagar (neto retenciones)"})

    create_journal_entry(
        tenant_id=tenant_id, created_by=created_by,
        entry_type="EXPENSE",
        description=f"Gasto {expense.expense_number}: {concept}",
        lines=lines,
        source_document_type="expense", source_document_id=str(expense.id),
    )

    db.session.commit()
    return _expense_to_dict(expense)


def pay_expense(tenant_id: str, expense_id: str, user_id: str,
                payment_method: str = "cash") -> dict:
    """Pay a previously caused (pending) expense."""
    expense = Expense.query.filter_by(id=expense_id, tenant_id=tenant_id).first()
    if not expense:
        raise ValueError("Gasto no encontrado")
    if expense.payment_status == "paid":
        raise ValueError("El gasto ya fue pagado")

    expense.payment_status = "paid"
    expense.payment_method = payment_method
    expense.paid_at = datetime.now(timezone.utc)

    # Accounting: DB 2335 CxP | CR 1105/1110
    # Use net amount (total - withholdings already recorded when expense was caused)
    withholdings = calculate_withholdings(tenant_id, Decimal(str(expense.amount)), "purchases")
    total_withholdings = sum(Decimal(str(w["amount"])) for w in withholdings)
    net_payable = float(Decimal(str(expense.total_amount)) - total_withholdings)

    cash_account = "1105" if payment_method == "cash" else "1110"
    create_journal_entry(
        tenant_id=tenant_id, created_by=user_id,
        entry_type="PAYMENT",
        description=f"Pago gasto {expense.expense_number}",
        lines=[
            {"puc_code": "2335", "debit": net_payable, "credit": 0,
             "description": "Pago gasto causado"},
            {"puc_code": cash_account, "debit": 0, "credit": net_payable,
             "description": f"Egreso por {expense.concept}"},
        ],
        source_document_type="expense_payment", source_document_id=str(expense.id),
    )

    db.session.commit()
    return _expense_to_dict(expense)


def get_expenses(tenant_id: str, page: int = 1, per_page: int = 20) -> dict:
    q = Expense.query.filter_by(tenant_id=tenant_id, status="active")
    total = q.count()
    expenses = q.order_by(Expense.created_at.desc()).offset(
        (page - 1) * per_page).limit(per_page).all()
    return {
        "data": [_expense_to_dict(e) for e in expenses],
        "pagination": {"page": page, "per_page": per_page, "total": total},
    }


# ── Period Reopen ────────────────────────────────────────────────

def reopen_period(tenant_id: str, year: int, month: int, user_id: str, reason: str = "") -> dict:
    """Reopen a closed period. Only if no subsequent period is closed. Reverses closing entry if December."""
    period = AccountingPeriod.query.filter_by(
        tenant_id=tenant_id, year=year, month=month
    ).first()
    if not period:
        raise ValueError(f"Periodo {year}-{month:02d} no encontrado")
    if period.status != "closed":
        raise ValueError(f"Periodo {year}-{month:02d} no está cerrado (estado: {period.status})")

    # Check no subsequent closed period
    later = AccountingPeriod.query.filter(
        AccountingPeriod.tenant_id == tenant_id,
        AccountingPeriod.status == "closed",
        db.or_(
            AccountingPeriod.year > year,
            db.and_(AccountingPeriod.year == year, AccountingPeriod.month > month),
        ),
    ).first()
    if later:
        raise ValueError(f"No se puede reabrir: periodo {later.year}-{later.month:02d} ya está cerrado")

    # If December, reverse the closing entry
    if month == 12:
        closing_entry = JournalEntry.query.filter_by(
            tenant_id=tenant_id, period_id=period.id,
            entry_type="CLOSING", is_reversed=False,
        ).first()
        if closing_entry:
            reverse_lines = []
            for line in closing_entry.lines:
                reverse_lines.append({
                    "puc_code": line.account.puc_code,
                    "debit": float(line.credit_amount),
                    "credit": float(line.debit_amount),
                    "description": f"Reversa cierre: {line.description or ''}",
                })
            if reverse_lines:
                create_journal_entry(
                    tenant_id=tenant_id, created_by=user_id,
                    entry_type="REVERSAL",
                    description=f"Reversa cierre anual {year}-{month:02d}. Motivo: {reason or 'Sin motivo'}",
                    lines=reverse_lines,
                    source_document_type="period_reopen",
                    source_document_id=str(period.id),
                )
            closing_entry.is_reversed = True

    period.status = "open"
    period.closed_at = None
    period.closed_by = None
    db.session.commit()
    return _period_to_dict(period)


# ── Monthly Close (automated) ───────────────────────────────────

def monthly_close(tenant_id: str, year: int, month: int, user_id: str) -> dict:
    """Monthly close: freeze period. Only December generates the annual closing entry."""
    # Calculate income, expenses, costs for the period
    balance = get_trial_balance(tenant_id, year, month)
    period = get_or_create_period(tenant_id, datetime(year, month, 1, tzinfo=timezone.utc))

    if period.status == "closed":
        raise ValueError(f"Periodo {year}-{month:02d} ya está cerrado")

    income_total = Decimal("0")
    expense_total = Decimal("0")
    cost_total = Decimal("0")

    for acc in balance["accounts"]:
        if acc["account_type"] == "income":
            income_total += Decimal(str(acc["balance"]))
        elif acc["account_type"] == "expense":
            expense_total += Decimal(str(acc["balance"]))
        elif acc["account_type"] == "cost":
            cost_total += Decimal(str(acc["balance"]))

    net_income = income_total - expense_total - cost_total

    # Only December generates the annual closing journal entry (NIIF/PUC)
    if month == 12 and (income_total > 0 or expense_total > 0 or cost_total > 0):
        closing_lines = []

        # Close income accounts (debit to zero them)
        for acc in balance["accounts"]:
            if acc["account_type"] == "income" and abs(acc["balance"]) > 0.01:
                closing_lines.append({
                    "puc_code": acc["puc_code"],
                    "debit": abs(acc["balance"]) if acc["balance"] > 0 else 0,
                    "credit": abs(acc["balance"]) if acc["balance"] < 0 else 0,
                    "description": f"Cierre anual {acc['name']}",
                })

        # Close expense/cost accounts (credit to zero them)
        for acc in balance["accounts"]:
            if acc["account_type"] in ("expense", "cost") and abs(acc["balance"]) > 0.01:
                closing_lines.append({
                    "puc_code": acc["puc_code"],
                    "debit": 0,
                    "credit": abs(acc["balance"]),
                    "description": f"Cierre anual {acc['name']}",
                })

        # Net to equity: 3605 (Utilidad, credit-normal) or 3610 (Pérdida, debit-normal)
        if net_income > 0:
            closing_lines.append({
                "puc_code": "3605", "debit": 0, "credit": float(net_income),
                "description": "Utilidad del ejercicio",
            })
        elif net_income < 0:
            closing_lines.append({
                "puc_code": "3610", "debit": float(abs(net_income)), "credit": 0,
                "description": "Pérdida del ejercicio",
            })

        if closing_lines:
            create_journal_entry(
                tenant_id=tenant_id, created_by=user_id,
                entry_type="CLOSING",
                description=f"Cierre anual {year}",
                lines=closing_lines,
                source_document_type="period_close",
                source_document_id=str(period.id),
            )

    # Close (freeze) the period
    period.status = "closed"
    period.closed_at = datetime.now(timezone.utc)
    period.closed_by = user_id
    db.session.commit()

    is_annual = month == 12
    return {
        "period": _period_to_dict(period),
        "income": float(income_total),
        "expenses": float(expense_total),
        "costs": float(cost_total),
        "net_income": float(net_income),
        "is_annual_close": is_annual,
        "message": f"Cierre anual {year} completado. Asiento contable generado." if is_annual else f"Periodo {year}-{month:02d} cerrado. No se pueden crear movimientos en este mes.",
    }


# ── Opening Balance (Saldos Iniciales) ──────────────────────────


def get_inventory_accounting_balance(tenant_id: str) -> float:
    """Return the current accounting balance of account 1435 (Inventory) from journal lines.
    Positive = debit balance (normal for assets). Negative = inconsistency."""
    account = ChartOfAccount.query.filter_by(
        tenant_id=tenant_id, puc_code="1435"
    ).first()
    if not account:
        return 0.0

    result = db.session.query(
        func.coalesce(func.sum(JournalLine.debit_amount), 0).label("total_debit"),
        func.coalesce(func.sum(JournalLine.credit_amount), 0).label("total_credit"),
    ).join(JournalEntry, JournalLine.entry_id == JournalEntry.id).filter(
        JournalEntry.tenant_id == tenant_id,
        JournalLine.account_id == account.id,
    ).first()

    return float((result.total_debit or 0) - (result.total_credit or 0))


def get_inventory_physical_value(tenant_id: str) -> float:
    """Return the total physical inventory value (stock * cost_average)."""
    from app.modules.inventory.models import Product
    products = Product.query.filter_by(tenant_id=tenant_id, is_active=True).filter(
        Product.deleted_at.is_(None)
    ).all()
    total = sum(
        float(p.stock_current) * float(p.cost_average or p.purchase_price or 0)
        for p in products
    )
    return round(total, 2)


def create_opening_balance(
    tenant_id: str, user_id: str, opening_date: str,
    cash: float = 0, bank: float = 0,
    receivables: float = 0, payables: float = 0,
    capital: float = 0, include_inventory: bool = True,
    equity_account: str = "3105",
) -> dict:
    """Create the opening balance entry for a tenant. Only one per tenant.

    Args:
        equity_account: PUC code for equity counterpart.
            '3105' = Capital social (new business),
            '3710' = Utilidades acumuladas (existing business).
    """
    from app.modules.inventory.models import Product

    # Validate equity account choice
    if equity_account not in ("3105", "3710"):
        equity_account = "3105"

    # Check no existing OPENING
    existing = JournalEntry.query.filter_by(
        tenant_id=tenant_id, entry_type="OPENING"
    ).first()
    if existing:
        raise ValueError("Ya existe un asiento de apertura. Use 'Corregir apertura' si necesita cambios.")

    # Parse date
    try:
        dt = datetime.strptime(opening_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc)

    # Calculate inventory from existing products
    inventory_value = 0
    if include_inventory:
        inventory_value = get_inventory_physical_value(tenant_id)

    # Account for any inventory already booked (e.g., from product creation entries)
    already_booked = get_inventory_accounting_balance(tenant_id)
    inventory_to_book = max(inventory_value - max(already_booked, 0), 0)

    # Calculate retained earnings by difference (use inventory_to_book, not inventory_value)
    total_assets = cash + bank + receivables + inventory_to_book
    total_liabilities = payables
    retained_earnings = total_assets - total_liabilities - capital
    if retained_earnings < 0:
        retained_earnings = 0
        capital = total_assets - total_liabilities  # Adjust capital

    # Build lines
    lines = []
    if cash > 0:
        lines.append({"puc_code": "1105", "debit": cash, "credit": 0, "description": "Saldo inicial caja"})
    if bank > 0:
        lines.append({"puc_code": "1110", "debit": bank, "credit": 0, "description": "Saldo inicial bancos"})
    if inventory_to_book > 0:
        lines.append({"puc_code": "1435", "debit": inventory_to_book, "credit": 0, "description": "Inventario inicial (calculado)"})
    if receivables > 0:
        lines.append({"puc_code": "1305", "debit": receivables, "credit": 0, "description": "Saldo inicial clientes (CxC)"})
    if payables > 0:
        lines.append({"puc_code": "2205", "debit": 0, "credit": payables, "description": "Saldo inicial proveedores (CxP)"})
    if capital > 0:
        equity_label = "Capital social" if equity_account == "3105" else "Utilidades acumuladas"
        lines.append({"puc_code": equity_account, "debit": 0, "credit": capital, "description": equity_label})
    if retained_earnings > 0:
        lines.append({"puc_code": "3710", "debit": 0, "credit": retained_earnings, "description": "Utilidades acumuladas"})

    if not lines:
        raise ValueError("Ingrese al menos un saldo para crear el asiento de apertura")

    entry = create_journal_entry(
        tenant_id=tenant_id, created_by=user_id,
        entry_type="OPENING",
        description=f"Asiento de apertura - {opening_date}",
        lines=lines,
        source_document_type="opening_balance",
        entry_date=dt,
    )

    db.session.commit()

    return {
        "entry": entry,
        "summary": {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "capital": capital,
            "retained_earnings": retained_earnings,
            "inventory_value": inventory_value,
            "inventory_already_booked": already_booked,
            "inventory_booked_now": inventory_to_book,
        }
    }


def get_opening_balance(tenant_id: str) -> dict:
    """Check if opening balance exists."""
    existing = JournalEntry.query.filter_by(
        tenant_id=tenant_id, entry_type="OPENING"
    ).first()
    if not existing:
        return {"exists": False}

    lines = []
    for line in existing.lines:
        lines.append({
            "puc_code": line.account.puc_code,
            "name": line.account.name,
            "debit": float(line.debit_amount),
            "credit": float(line.credit_amount),
        })
    return {
        "exists": True,
        "entry_date": existing.entry_date.isoformat(),
        "lines": lines,
    }


# ── Withholding Calculation ──────────────────────────────────────

UVT_VALUE = Decimal("49799")  # UVT 2025 — update annually


def calculate_withholdings(tenant_id: str, base_amount: Decimal, applies_to: str = "purchases") -> list:
    """Calculate applicable withholdings for a transaction. Returns list of {puc_code, amount, name}."""
    configs = WithholdingConfig.query.filter(
        WithholdingConfig.tenant_id == tenant_id,
        WithholdingConfig.is_active.is_(True),
        WithholdingConfig.applies_to.in_([applies_to, "both"]),
    ).all()

    results = []
    for config in configs:
        # Check UVT threshold
        threshold = config.base_uvt * UVT_VALUE if config.base_uvt > 0 else Decimal("0")
        if base_amount >= threshold:
            amount = (base_amount * config.rate / 100).quantize(TWO_PLACES)
            if amount > 0:
                results.append({
                    "puc_code": config.puc_code,
                    "amount": float(amount),
                    "name": config.name,
                    "type": config.type,
                    "rate": float(config.rate),
                })
    return results


# ── Withholding Seed ─────────────────────────────────────────────

WITHHOLDING_SEED = [
    ("retefuente", "Retención en la fuente - Compras", 2.5, 27, "2365", "purchases"),
    ("reteiva", "Retención de IVA - 15%", 15.0, 0, "2368", "purchases"),
]


def seed_withholdings(tenant_id: str) -> int:
    """Seed default withholding configs for a tenant."""
    existing = WithholdingConfig.query.filter_by(tenant_id=tenant_id).count()
    if existing > 0:
        return existing

    for wtype, name, rate, base_uvt, puc, applies in WITHHOLDING_SEED:
        config = WithholdingConfig(
            tenant_id=tenant_id, type=wtype, name=name,
            rate=Decimal(str(rate)), base_uvt=Decimal(str(base_uvt)),
            puc_code=puc, applies_to=applies,
        )
        db.session.add(config)
    db.session.commit()
    return len(WITHHOLDING_SEED)


def get_withholdings(tenant_id: str) -> list:
    configs = WithholdingConfig.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).all()
    return [{
        "id": str(c.id),
        "type": c.type,
        "name": c.name,
        "rate": float(c.rate),
        "base_uvt": float(c.base_uvt),
        "puc_code": c.puc_code,
        "applies_to": c.applies_to,
    } for c in configs]


# ── PUC CRUD ─────────────────────────────────────────────────────

def create_account(
    tenant_id: str, puc_code: str, name: str,
    account_type: str, normal_balance: str,
    parent_code: str = None,
) -> dict:
    """Create a new account in the chart of accounts."""
    existing = ChartOfAccount.query.filter_by(
        tenant_id=tenant_id, puc_code=puc_code
    ).first()
    if existing:
        raise ValueError(f"La cuenta {puc_code} ya existe")

    valid_types = ("asset", "liability", "equity", "income", "expense", "cost")
    if account_type not in valid_types:
        raise ValueError(f"Tipo de cuenta inválido. Debe ser: {', '.join(valid_types)}")

    if normal_balance not in ("debit", "credit"):
        raise ValueError("Balance normal debe ser 'debit' o 'credit'")

    account = ChartOfAccount(
        tenant_id=tenant_id,
        puc_code=puc_code,
        name=name,
        account_type=account_type,
        normal_balance=normal_balance,
        parent_code=parent_code,
        is_system=False,
    )
    db.session.add(account)
    db.session.commit()
    return _account_to_dict(account)


def update_account(tenant_id: str, account_id: str, **kwargs) -> dict:
    """Update account name or toggle active. System accounts: name not editable."""
    account = ChartOfAccount.query.filter_by(
        id=account_id, tenant_id=tenant_id
    ).first()
    if not account:
        raise ValueError("Cuenta no encontrada")

    if account.is_system and "name" in kwargs:
        raise ValueError("No se puede editar el nombre de cuentas del sistema")

    for field in ("name", "is_active", "parent_code"):
        if field in kwargs and kwargs[field] is not None:
            setattr(account, field, kwargs[field])

    db.session.commit()
    return _account_to_dict(account)


def delete_account(tenant_id: str, account_id: str) -> dict:
    """Delete an account. Only non-system accounts with no journal entries."""
    account = ChartOfAccount.query.filter_by(
        id=account_id, tenant_id=tenant_id
    ).first()
    if not account:
        raise ValueError("Cuenta no encontrada")

    if account.is_system:
        raise ValueError("No se pueden eliminar cuentas del sistema. Use 'inactivar' en su lugar.")

    # Check if account has any journal lines
    has_movements = JournalLine.query.filter_by(account_id=account.id).first()
    if has_movements:
        raise ValueError(
            f"La cuenta {account.puc_code} tiene movimientos contables registrados. "
            "No se puede eliminar — use 'inactivar' para que no aparezca en nuevos asientos."
        )

    db.session.delete(account)
    db.session.commit()
    return {"deleted": True, "puc_code": account.puc_code, "name": account.name}


def _account_to_dict(a: ChartOfAccount) -> dict:
    return {
        "id": str(a.id),
        "puc_code": a.puc_code,
        "name": a.name,
        "account_type": a.account_type,
        "normal_balance": a.normal_balance,
        "parent_code": a.parent_code,
        "is_system": a.is_system,
        "is_active": a.is_active,
    }


# ── PUC Seed ──────────────────────────────────────────────────────

PUC_SEED = [
    # PUC Colombia completo para PYMES / Microempresas (Decreto 2650/1993 + NIIF Grupo 3)
    # (code, name, type, normal_balance)

    # ════════════════════════════════════════════════════════════
    # CLASE 1 — ACTIVOS
    # ════════════════════════════════════════════════════════════

    # 11 - Efectivo y equivalentes
    ("1105", "Caja", "asset", "debit"),
    ("110505", "Caja general", "asset", "debit"),
    ("110510", "Cajas menores", "asset", "debit"),
    ("1110", "Bancos", "asset", "debit"),
    ("111005", "Bancos moneda nacional", "asset", "debit"),
    ("1115", "Cuentas de ahorro", "asset", "debit"),
    ("111505", "Cuentas de ahorro moneda nacional", "asset", "debit"),
    ("1120", "Cuentas corrientes", "asset", "debit"),

    # 12 - Inversiones
    ("1205", "Acciones y aportes", "asset", "debit"),
    ("1225", "Certificados (CDT)", "asset", "debit"),

    # 13 - Deudores
    ("1305", "Clientes", "asset", "debit"),
    ("130505", "Clientes nacionales", "asset", "debit"),
    ("1310", "Cuentas por cobrar a socios", "asset", "debit"),
    ("1325", "Cuentas por cobrar empleados", "asset", "debit"),
    ("1330", "Anticipos y avances", "asset", "debit"),
    ("133005", "Anticipos a proveedores", "asset", "debit"),
    ("1335", "Depósitos", "asset", "debit"),
    ("1345", "Ingresos por cobrar", "asset", "debit"),
    ("1355", "Anticipo de impuesto de renta", "asset", "debit"),
    ("1360", "Anticipo de industria y comercio", "asset", "debit"),
    ("1365", "Retención en la fuente a favor", "asset", "debit"),
    ("1370", "Retención de IVA a favor", "asset", "debit"),
    ("1380", "Deudores varios", "asset", "debit"),
    ("1390", "Deudas de difícil cobro", "asset", "debit"),
    ("1399", "Provisión deudores", "asset", "credit"),

    # 14 - Inventarios
    ("1405", "Materias primas", "asset", "debit"),
    ("1435", "Mercancías no fabricadas por la empresa", "asset", "debit"),
    ("143505", "Mercancías para la venta", "asset", "debit"),
    ("1440", "Bienes raíces para la venta", "asset", "debit"),
    ("1455", "Materiales y repuestos", "asset", "debit"),
    ("1465", "Inventarios en tránsito", "asset", "debit"),
    ("1499", "Provisión por obsolescencia", "asset", "credit"),

    # 15 - Propiedad, planta y equipo
    ("1504", "Terrenos", "asset", "debit"),
    ("1508", "Edificaciones", "asset", "debit"),
    ("1512", "Maquinaria y equipo", "asset", "debit"),
    ("1516", "Equipo de oficina", "asset", "debit"),
    ("1520", "Equipo de computación", "asset", "debit"),
    ("1524", "Equipo de comunicación", "asset", "debit"),
    ("1528", "Equipo de transporte", "asset", "debit"),
    ("1540", "Flota y equipo de transporte", "asset", "debit"),
    ("1592", "Depreciación acumulada", "asset", "credit"),
    ("159205", "Depreciación edificaciones", "asset", "credit"),
    ("159210", "Depreciación maquinaria", "asset", "credit"),
    ("159215", "Depreciación equipo oficina", "asset", "credit"),
    ("159220", "Depreciación equipo cómputo", "asset", "credit"),
    ("159225", "Depreciación vehículos", "asset", "credit"),

    # 16 - Intangibles
    ("1605", "Crédito mercantil (Good Will)", "asset", "debit"),
    ("1610", "Marcas", "asset", "debit"),
    ("1615", "Patentes", "asset", "debit"),
    ("1620", "Licencias y software", "asset", "debit"),
    ("1698", "Amortización acumulada intangibles", "asset", "credit"),

    # 17 - Diferidos
    ("1705", "Gastos pagados por anticipado", "asset", "debit"),
    ("170505", "Seguros pagados por anticipado", "asset", "debit"),
    ("170510", "Arrendamiento pagado por anticipado", "asset", "debit"),
    ("1710", "Cargos diferidos", "asset", "debit"),

    # 18 - Otros activos
    ("1805", "Bienes de arte y cultura", "asset", "debit"),
    ("1895", "Diversos", "asset", "debit"),

    # ════════════════════════════════════════════════════════════
    # CLASE 2 — PASIVOS
    # ════════════════════════════════════════════════════════════

    # 21 - Obligaciones financieras
    ("2105", "Obligaciones financieras - bancos", "liability", "credit"),
    ("210505", "Pagarés bancarios", "liability", "credit"),
    ("2115", "Corporaciones financieras", "liability", "credit"),
    ("2120", "Otras obligaciones", "liability", "credit"),

    # 22 - Proveedores
    ("2205", "Proveedores nacionales", "liability", "credit"),
    ("220505", "Proveedores nacionales (detalle)", "liability", "credit"),
    ("2210", "Proveedores del exterior", "liability", "credit"),

    # 23 - Cuentas por pagar
    ("2305", "Cuentas por pagar a socios", "liability", "credit"),
    ("2335", "Costos y gastos por pagar", "liability", "credit"),
    ("233505", "Honorarios por pagar", "liability", "credit"),
    ("233510", "Servicios por pagar", "liability", "credit"),
    ("233515", "Arrendamiento por pagar", "liability", "credit"),
    ("2345", "Acreedores oficiales", "liability", "credit"),
    ("2355", "Deudas con socios", "liability", "credit"),
    ("2360", "Dividendos por pagar", "liability", "credit"),
    ("2365", "Retención en la fuente por pagar", "liability", "credit"),
    ("236505", "Retención compras 2.5%", "liability", "credit"),
    ("236510", "Retención servicios 4%", "liability", "credit"),
    ("236515", "Retención honorarios 11%", "liability", "credit"),
    ("236520", "Retención salarios", "liability", "credit"),
    ("2366", "Retención ICA por pagar", "liability", "credit"),
    ("2367", "Impuesto a las ventas retenido", "liability", "credit"),
    ("2368", "Retención de IVA por pagar", "liability", "credit"),
    ("2370", "IVA por pagar", "liability", "credit"),
    ("237005", "IVA generado 19%", "liability", "credit"),
    ("237010", "IVA generado 5%", "liability", "credit"),
    ("237015", "IVA descontable", "liability", "debit"),
    ("2380", "Acreedores varios", "liability", "credit"),

    # 24 - Impuestos
    ("2404", "Impuesto de renta por pagar", "liability", "credit"),
    ("2408", "Impuesto sobre las ventas (IVA)", "liability", "credit"),
    ("2412", "Industria y comercio por pagar", "liability", "credit"),
    ("2416", "Impuesto SIMPLE por pagar", "liability", "credit"),

    # 25 - Obligaciones laborales
    ("2505", "Salarios por pagar", "liability", "credit"),
    ("2510", "Cesantías consolidadas", "liability", "credit"),
    ("2515", "Intereses sobre cesantías", "liability", "credit"),
    ("2520", "Prima de servicios", "liability", "credit"),
    ("2525", "Vacaciones consolidadas", "liability", "credit"),
    ("2530", "Prestaciones extralegales", "liability", "credit"),
    ("2550", "Aportes a entidades (SENA, ICBF, CCF)", "liability", "credit"),
    ("2555", "Seguridad social por pagar (EPS, AFP, ARL)", "liability", "credit"),

    # 26 - Pasivos estimados
    ("2605", "Para obligaciones laborales", "liability", "credit"),
    ("2610", "Para obligaciones fiscales", "liability", "credit"),
    ("2615", "Para contingencias", "liability", "credit"),

    # 27 - Diferidos
    ("2705", "Ingresos recibidos por anticipado", "liability", "credit"),
    ("2710", "Abonos diferidos", "liability", "credit"),

    # 28 - Otros pasivos
    ("2805", "Anticipos y avances recibidos", "liability", "credit"),
    ("2810", "Depósitos recibidos", "liability", "credit"),
    ("2895", "Diversos", "liability", "credit"),

    # ════════════════════════════════════════════════════════════
    # CLASE 3 — PATRIMONIO
    # ════════════════════════════════════════════════════════════
    ("3105", "Capital social", "equity", "credit"),
    ("310505", "Capital suscrito y pagado", "equity", "credit"),
    ("3115", "Aportes sociales", "equity", "credit"),
    ("3205", "Prima en colocación de acciones", "equity", "credit"),
    ("3305", "Reservas obligatorias", "equity", "credit"),
    ("3310", "Reservas estatutarias", "equity", "credit"),
    ("3315", "Reservas ocasionales", "equity", "credit"),
    ("3605", "Utilidad del ejercicio", "equity", "credit"),
    ("3610", "Pérdida del ejercicio", "equity", "debit"),
    ("3710", "Utilidades acumuladas", "equity", "credit"),
    ("3715", "Pérdidas acumuladas", "equity", "debit"),

    # ════════════════════════════════════════════════════════════
    # CLASE 4 — INGRESOS
    # ════════════════════════════════════════════════════════════
    ("4135", "Comercio al por mayor y menor", "income", "credit"),
    ("413505", "Ventas gravadas 19%", "income", "credit"),
    ("413510", "Ventas gravadas 5%", "income", "credit"),
    ("413515", "Ventas excluidas de IVA", "income", "credit"),
    ("413520", "Ventas exentas de IVA", "income", "credit"),
    ("4175", "Devoluciones en ventas", "income", "debit"),
    ("417505", "Devoluciones ventas gravadas", "income", "debit"),
    ("4205", "Otras ventas", "income", "credit"),
    ("4210", "Ingresos financieros", "income", "credit"),
    ("421005", "Intereses recibidos", "income", "credit"),
    ("4215", "Dividendos y participaciones", "income", "credit"),
    ("4220", "Arrendamientos", "income", "credit"),
    ("4245", "Utilidad en venta de activos", "income", "credit"),
    ("4250", "Recuperaciones", "income", "credit"),
    ("4255", "Indemnizaciones", "income", "credit"),
    ("4295", "Ingresos diversos", "income", "credit"),

    # ════════════════════════════════════════════════════════════
    # CLASE 5 — GASTOS
    # ════════════════════════════════════════════════════════════

    # 51 - Gastos de administración y personal
    ("5105", "Gastos de personal - sueldos", "expense", "debit"),
    ("510505", "Sueldo básico", "expense", "debit"),
    ("510510", "Horas extras y recargos", "expense", "debit"),
    ("510515", "Auxilio de transporte", "expense", "debit"),
    ("5110", "Comisiones", "expense", "debit"),
    ("5115", "Honorarios", "expense", "debit"),
    ("511505", "Honorarios contador", "expense", "debit"),
    ("511510", "Honorarios asesor legal", "expense", "debit"),
    ("5120", "Servicios temporales", "expense", "debit"),
    ("5130", "Cesantías", "expense", "debit"),
    ("5131", "Intereses sobre cesantías", "expense", "debit"),
    ("5132", "Prima de servicios", "expense", "debit"),
    ("5133", "Vacaciones", "expense", "debit"),
    ("5134", "Dotación y suministros", "expense", "debit"),
    ("5135", "Servicios públicos", "expense", "debit"),
    ("513505", "Energía eléctrica", "expense", "debit"),
    ("513510", "Acueducto y alcantarillado", "expense", "debit"),
    ("513515", "Gas", "expense", "debit"),
    ("513520", "Teléfono e internet", "expense", "debit"),
    ("5140", "Seguridad social", "expense", "debit"),
    ("514005", "Aportes EPS", "expense", "debit"),
    ("514010", "Aportes AFP (pensión)", "expense", "debit"),
    ("514015", "Aportes ARL", "expense", "debit"),
    ("5145", "Aportes parafiscales", "expense", "debit"),
    ("514505", "SENA", "expense", "debit"),
    ("514510", "ICBF", "expense", "debit"),
    ("514515", "Caja de compensación", "expense", "debit"),
    ("5150", "Seguros", "expense", "debit"),
    ("515005", "Seguro del local", "expense", "debit"),
    ("515010", "Seguro de vehículo", "expense", "debit"),
    ("5155", "Gastos de viaje", "expense", "debit"),
    ("5160", "Arrendamiento", "expense", "debit"),
    ("516005", "Arrendamiento local comercial", "expense", "debit"),
    ("516010", "Arrendamiento equipo", "expense", "debit"),
    ("5165", "Mantenimiento y reparaciones", "expense", "debit"),
    ("516505", "Mantenimiento local", "expense", "debit"),
    ("516510", "Mantenimiento equipo", "expense", "debit"),
    ("5170", "Publicidad y propaganda", "expense", "debit"),
    ("5175", "Capacitación", "expense", "debit"),
    ("5195", "Gastos diversos", "expense", "debit"),
    ("519505", "Papelería y útiles", "expense", "debit"),
    ("519510", "Elementos de aseo", "expense", "debit"),
    ("519515", "Gastos de representación", "expense", "debit"),
    ("519520", "Gastos legales y notariales", "expense", "debit"),
    ("519525", "Impuesto predial", "expense", "debit"),
    ("519530", "Impuesto de industria y comercio (ICA)", "expense", "debit"),
    ("519535", "Tasas y contribuciones", "expense", "debit"),
    ("519540", "Otros impuestos y gravámenes", "expense", "debit"),
    ("519545", "Comisiones plataformas digitales", "expense", "debit"),
    ("519550", "Suscripciones de software", "expense", "debit"),

    # 5155 - Gastos de viaje y transporte
    ("515505", "Fletes y acarreos", "expense", "debit"),
    ("515510", "Pasajes y viáticos", "expense", "debit"),

    # 5165 - Mantenimiento (subcuenta adicional)
    ("516515", "Mantenimiento software y sistemas", "expense", "debit"),

    # 5175 - Publicidad
    ("5175", "Publicidad y propaganda", "expense", "debit"),
    ("517505", "Publicidad en redes sociales", "expense", "debit"),
    ("517510", "Material impreso y volantes", "expense", "debit"),

    # 52 - Depreciación y amortización
    ("5205", "Depreciación propiedad planta y equipo", "expense", "debit"),
    ("520505", "Depreciación edificaciones", "expense", "debit"),
    ("520510", "Depreciación maquinaria", "expense", "debit"),
    ("520515", "Depreciación equipo oficina", "expense", "debit"),
    ("520520", "Depreciación equipo cómputo", "expense", "debit"),
    ("520525", "Depreciación vehículos", "expense", "debit"),
    ("5210", "Amortización de intangibles", "expense", "debit"),

    # 53 - Gastos financieros
    ("5305", "Gastos financieros", "expense", "debit"),
    ("530505", "Comisiones bancarias", "expense", "debit"),
    ("530510", "Intereses préstamos", "expense", "debit"),
    ("530515", "Gravamen movimientos financieros (4x1000)", "expense", "debit"),
    ("530520", "Multas y sanciones", "expense", "debit"),

    # 54 - Impuestos asumidos como gasto
    ("5405", "Impuesto de industria y comercio", "expense", "debit"),
    ("5410", "Impuesto predial", "expense", "debit"),
    ("5415", "Impuesto de vehículos", "expense", "debit"),

    # ════════════════════════════════════════════════════════════
    # CLASE 6 — COSTOS DE VENTAS
    # ════════════════════════════════════════════════════════════
    ("6135", "Costo de ventas mercancías", "cost", "debit"),
    ("613505", "Costo mercancías gravadas 19%", "cost", "debit"),
    ("613510", "Costo mercancías gravadas 5%", "cost", "debit"),
    ("613515", "Costo mercancías exentas/excluidas", "cost", "debit"),
    ("6205", "Compras de mercancías", "cost", "debit"),
    ("6225", "Devoluciones en compras", "cost", "credit"),
]


def seed_chart_of_accounts(tenant_id: str) -> int:
    """Seed the PUC for a tenant. Incremental — adds missing accounts."""
    existing_codes = set()
    for row in ChartOfAccount.query.filter_by(tenant_id=tenant_id).all():
        existing_codes.add(row.puc_code)

    added = 0
    for code, name, acc_type, normal in PUC_SEED:
        if code in existing_codes:
            continue
        account = ChartOfAccount(
            tenant_id=tenant_id, puc_code=code, name=name,
            account_type=acc_type, normal_balance=normal, is_system=True,
        )
        db.session.add(account)
        added += 1

    db.session.commit()
    return added


def get_chart_of_accounts(tenant_id: str) -> list:
    """Get all accounts for a tenant (active and inactive)."""
    accounts = ChartOfAccount.query.filter_by(
        tenant_id=tenant_id
    ).order_by(ChartOfAccount.puc_code).all()
    return [_account_to_dict(a) for a in accounts]


def get_journal_entries(
    tenant_id: str, page: int = 1, per_page: int = 20,
    entry_type: str = None,
) -> dict:
    """List journal entries with pagination."""
    q = JournalEntry.query.filter_by(tenant_id=tenant_id)
    if entry_type:
        q = q.filter_by(entry_type=entry_type)

    total = q.count()
    entries = q.order_by(JournalEntry.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return {
        "data": [_entry_to_dict(e) for e in entries],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "has_next": page * per_page < total,
        },
    }


# ── Serializers ───────────────────────────────────────────────────

def _expense_to_dict(e: Expense) -> dict:
    return {
        "id": str(e.id),
        "expense_number": e.expense_number,
        "expense_date": e.expense_date.isoformat(),
        "puc_code": e.puc_code,
        "concept": e.concept,
        "amount": float(e.amount),
        "tax_amount": float(e.tax_amount),
        "total_amount": float(e.total_amount),
        "payment_status": e.payment_status,
        "payment_method": e.payment_method,
        "status": e.status,
    }


def _period_to_dict(p: AccountingPeriod) -> dict:
    return {
        "id": str(p.id),
        "year": p.year, "month": p.month,
        "status": p.status,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
    }


def _entry_to_dict(e: JournalEntry) -> dict:
    return {
        "id": str(e.id),
        "entry_date": e.entry_date.isoformat(),
        "entry_type": e.entry_type,
        "description": e.description,
        "total_debit": float(e.total_debit),
        "total_credit": float(e.total_credit),
        "is_reversed": e.is_reversed,
        "source_document_type": e.source_document_type,
        "source_document_id": str(e.source_document_id) if e.source_document_id else None,
        "lines": [_line_to_dict(l) for l in e.lines],
    }


def _line_to_dict(l: JournalLine) -> dict:
    return {
        "account_puc": l.account.puc_code if l.account else None,
        "account_name": l.account.name if l.account else None,
        "debit": float(l.debit_amount),
        "credit": float(l.credit_amount),
        "description": l.description,
    }
