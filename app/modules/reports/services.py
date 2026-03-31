"""Reports services — Dashboard, sales reports, inventory, P&L."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, case, desc, and_, text

BOGOTA_TZ = ZoneInfo("America/Bogota")


def _today_bogota():
    """Get today's date in Colombia timezone."""
    return datetime.now(BOGOTA_TZ).strftime("%Y-%m-%d")


def _date_in_bogota(column):
    """SQL expression: convert timestamptz column to date in Bogota timezone."""
    return func.date(func.timezone("America/Bogota", column))

from app.extensions import db
from app.modules.pos.models import Sale, SaleItem, Payment, CreditNote
from app.modules.inventory.models import Product, StockMovement
from app.modules.accounting.models import ChartOfAccount, JournalEntry, JournalLine, AccountingPeriod
from app.modules.purchases.models import PurchaseOrder, SupplierPayment, PurchaseCreditNote, PurchaseDebitNote


# ── Dashboard ─────────────────────────────────────────────────────

def _parse_date_range(date_from: str = None, date_to: str = None):
    """Parse date range strings into timezone-aware datetimes. Defaults to today (Bogotá)."""
    now_bog = datetime.now(BOGOTA_TZ)
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BOGOTA_TZ)
            start = dt
        except ValueError:
            start = now_bog.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now_bog.replace(hour=0, minute=0, second=0, microsecond=0)

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BOGOTA_TZ)
            end = dt
        except ValueError:
            end = now_bog.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        end = now_bog.replace(hour=23, minute=59, second=59, microsecond=999999)

    return start, end


def get_dashboard(tenant_id: str, date: str = None, date_from: str = None, date_to: str = None) -> dict:
    """Main dashboard with KPIs, top products, alerts. Supports date range."""
    # Build date range filter
    if date and not date_from:
        # Legacy single-date: convert to range (full day)
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            date_from_dt = d.replace(hour=0, minute=0, second=0, tzinfo=BOGOTA_TZ)
            date_to_dt = d.replace(hour=23, minute=59, second=59, tzinfo=BOGOTA_TZ)
        except ValueError:
            date_from_dt, date_to_dt = _parse_date_range()
    else:
        date_from_dt, date_to_dt = _parse_date_range(date_from, date_to)

    # Date filter used in all queries — uses index (tenant_id, sale_date)
    def _sale_date_filter():
        return and_(
            Sale.tenant_id == tenant_id,
            Sale.status == "completed",
            Sale.sale_date >= date_from_dt,
            Sale.sale_date <= date_to_dt,
        )

    # Auto-mark overdue credit sales
    try:
        from app.modules.pos.services import mark_overdue_sales
        mark_overdue_sales(tenant_id)
    except Exception:
        pass

    # Sales KPIs
    sales_kpi = (
        db.session.query(
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total"),
            func.coalesce(func.sum(Sale.subtotal), 0).label("subtotal"),
            func.coalesce(func.sum(Sale.tax_amount), 0).label("tax"),
        )
        .filter(_sale_date_filter())
        .first()
    )

    # Cost of goods sold (from SaleItems)
    cost_kpi = (
        db.session.query(
            func.coalesce(func.sum(SaleItem.quantity * SaleItem.unit_cost), 0).label("cost"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(_sale_date_filter())
        .first()
    )
    total_cost = float(cost_kpi.cost or 0) if cost_kpi else 0
    total_with_tax = float(sales_kpi.total or 0)
    total_subtotal = float(sales_kpi.subtotal or 0)  # Revenue WITHOUT tax
    total_tax = float(sales_kpi.tax or 0)
    # Utilidad bruta = Ventas netas (sin IVA) - Costo de mercancía
    gross_profit = total_subtotal - total_cost
    margin_pct = round((gross_profit / total_subtotal * 100), 1) if total_subtotal > 0 else 0

    # Sales by payment method today
    payment_breakdown = (
        db.session.query(
            Payment.method,
            func.sum(Payment.amount).label("total"),
            func.count(Payment.id).label("count"),
        )
        .join(Sale, Payment.sale_id == Sale.id)
        .filter(_sale_date_filter())
        .group_by(Payment.method)
        .all()
    )

    # Top 5 products today (with cost for profit calculation)
    top_products = (
        db.session.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("qty_sold"),
            func.sum(SaleItem.total).label("revenue"),
            func.sum(SaleItem.quantity * SaleItem.unit_cost).label("cost"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(_sale_date_filter())
        .group_by(SaleItem.product_name)
        .order_by(desc("revenue"))
        .limit(5)
        .all()
    )

    # Low stock alerts
    low_stock = (
        Product.query.filter(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.deleted_at.is_(None),
            Product.stock_current <= Product.stock_minimum,
        )
        .order_by(Product.stock_current)
        .limit(10)
        .all()
    )

    # Pending purchase orders
    pending_po = (
        PurchaseOrder.query.filter(
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.status.in_(["sent", "partially_received"]),
        )
        .count()
    )

    # Purchases KPIs for today
    purchases_kpi = (
        db.session.query(
            func.count(func.distinct(PurchaseOrder.id)).label("count"),
            func.coalesce(func.sum(func.distinct(PurchaseOrder.total_amount)), 0).label("total"),
        )
        .filter(
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.status == "received",
            PurchaseOrder.received_at >= date_from_dt,
            PurchaseOrder.received_at <= date_to_dt,
        )
        .first()
    )

    # Sales by hour (for chart)
    sales_by_hour = (
        db.session.query(
            func.extract("hour", func.timezone("America/Bogota", Sale.sale_date)).label("hour"),
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total"),
        )
        .filter(_sale_date_filter())
        .group_by("hour")
        .order_by("hour")
        .all()
    )

    # CxP balance (total credit purchases - payments - credit notes)
    total_credit_purchases = db.session.query(
        func.coalesce(func.sum(PurchaseOrder.total_amount), 0)
    ).filter(
        PurchaseOrder.tenant_id == tenant_id,
        PurchaseOrder.payment_type == "credit",
        PurchaseOrder.status.in_(["received", "partially_received"]),
    ).scalar()

    total_supplier_payments = db.session.query(
        func.coalesce(func.sum(SupplierPayment.amount), 0)
    ).filter(
        SupplierPayment.tenant_id == tenant_id,
        SupplierPayment.status == "completed",
    ).scalar()

    total_purchase_cn = db.session.query(
        func.coalesce(func.sum(PurchaseCreditNote.total_amount), 0)
    ).filter(
        PurchaseCreditNote.tenant_id == tenant_id,
        PurchaseCreditNote.status == "active",
    ).scalar()

    total_purchase_dn = db.session.query(
        func.coalesce(func.sum(PurchaseDebitNote.total_amount), 0)
    ).filter(
        PurchaseDebitNote.tenant_id == tenant_id,
        PurchaseDebitNote.status == "active",
    ).scalar()

    cxp_balance = (
        float(total_credit_purchases)
        + float(total_purchase_dn)
        - float(total_supplier_payments)
        - float(total_purchase_cn)
    )

    return {
        "date_from": date_from_dt.isoformat(),
        "date_to": date_to_dt.isoformat(),
        "date": date_from_dt.strftime("%Y-%m-%d"),
        "sales": {
            "count": sales_kpi.count or 0,
            "revenue": total_with_tax,
            "subtotal": total_subtotal,
            "cost": total_cost,
            "gross_profit": gross_profit,
            "margin_pct": margin_pct,
            "tax": total_tax,
            "avg_ticket": round(total_with_tax / max(sales_kpi.count or 1, 1), 2),
        },
        "purchases": {
            "count": purchases_kpi.count or 0,
            "total": float(purchases_kpi.total or 0),
        },
        "cxp_balance": cxp_balance,
        "sales_by_hour": [
            {"hour": int(h.hour), "count": h.count, "total": float(h.total)}
            for h in sales_by_hour
        ],
        "payment_methods": [
            {"method": p.method, "total": float(p.total), "count": p.count}
            for p in payment_breakdown
        ],
        "top_products": [
            {
                "name": t.product_name,
                "qty_sold": float(t.qty_sold),
                "revenue": float(t.revenue),
                "cost": float(t.cost or 0),
                "profit": round(float(t.revenue) - float(t.cost or 0), 2),
                "margin_pct": round((float(t.revenue) - float(t.cost or 0)) / max(float(t.revenue), 0.01) * 100, 1),
            }
            for t in top_products
        ],
        "alerts": {
            "low_stock_count": len(low_stock),
            "low_stock_items": [
                {"name": p.name, "stock": float(p.stock_current), "minimum": float(p.stock_minimum)}
                for p in low_stock
            ],
            "pending_purchase_orders": pending_po,
        },
    }


# ── Sales Report ──────────────────────────────────────────────────

def get_sales_report(
    tenant_id: str, date_from: str, date_to: str,
    group_by: str = "day",
) -> dict:
    """Sales report grouped by day, week, or month."""
    if group_by == "day":
        date_trunc = func.date(Sale.sale_date)
    elif group_by == "week":
        date_trunc = func.date_trunc("week", Sale.sale_date)
    else:
        date_trunc = func.date_trunc("month", Sale.sale_date)

    rows = (
        db.session.query(
            date_trunc.label("period"),
            func.count(Sale.id).label("count"),
            func.sum(Sale.subtotal).label("subtotal"),
            func.sum(Sale.tax_amount).label("tax"),
            func.sum(Sale.total_amount).label("total"),
            func.avg(Sale.total_amount).label("avg_ticket"),
        )
        .filter(
            Sale.tenant_id == tenant_id,
            Sale.status == "completed",
            _date_in_bogota(Sale.sale_date) >= date_from,
            _date_in_bogota(Sale.sale_date) <= date_to,
        )
        .group_by("period")
        .order_by("period")
        .all()
    )

    # Top products in range
    top = (
        db.session.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.total).label("revenue"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.tenant_id == tenant_id,
            Sale.status == "completed",
            _date_in_bogota(Sale.sale_date) >= date_from,
            _date_in_bogota(Sale.sale_date) <= date_to,
        )
        .group_by(SaleItem.product_name)
        .order_by(desc("revenue"))
        .limit(20)
        .all()
    )

    # Totals
    total_revenue = sum(float(r.total or 0) for r in rows)
    total_count = sum(r.count or 0 for r in rows)

    # Returns (credit notes) in period
    total_returns = db.session.query(
        func.coalesce(func.sum(CreditNote.total_amount), 0)
    ).filter(
        CreditNote.tenant_id == tenant_id,
        _date_in_bogota(CreditNote.created_at) >= date_from,
        _date_in_bogota(CreditNote.created_at) <= date_to,
    ).scalar()
    total_returns = float(total_returns)
    net_revenue = total_revenue - total_returns

    return {
        "date_from": date_from,
        "date_to": date_to,
        "group_by": group_by,
        "periods": [
            {
                "period": str(r.period),
                "sales_count": r.count,
                "subtotal": float(r.subtotal or 0),
                "tax": float(r.tax or 0),
                "total": float(r.total or 0),
                "avg_ticket": round(float(r.avg_ticket or 0), 2),
            }
            for r in rows
        ],
        "top_products": [
            {"name": t.product_name, "quantity": float(t.qty), "revenue": float(t.revenue)}
            for t in top
        ],
        "summary": {
            "total_sales": total_count,
            "gross_revenue": total_revenue,
            "returns": total_returns,
            "net_revenue": net_revenue,
            "total_revenue": net_revenue,
            "avg_ticket": round(total_revenue / total_count, 2) if total_count > 0 else 0,
        },
    }


# ── Inventory Report ──────────────────────────────────────────────

def get_inventory_report(tenant_id: str) -> dict:
    """Current inventory valuation and status."""
    products = (
        Product.query.filter(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.deleted_at.is_(None),
        )
        .order_by(Product.name)
        .all()
    )

    items = []
    total_value = Decimal("0")
    total_cost = Decimal("0")
    low_stock_count = 0

    for p in products:
        value_at_sale = p.stock_current * p.sale_price
        value_at_cost = p.stock_current * p.cost_average
        total_value += value_at_sale
        total_cost += value_at_cost
        if p.is_low_stock:
            low_stock_count += 1

        items.append({
            "name": p.name,
            "sku": p.sku,
            "stock": float(p.stock_current),
            "minimum": float(p.stock_minimum),
            "is_low_stock": p.is_low_stock,
            "unit": p.unit,
            "sale_price": float(p.sale_price),
            "cost_average": float(p.cost_average),
            "value_at_sale": float(value_at_sale),
            "value_at_cost": float(value_at_cost),
        })

    return {
        "total_products": len(items),
        "low_stock_count": low_stock_count,
        "total_value_at_sale": float(total_value),
        "total_value_at_cost": float(total_cost),
        "potential_margin": float(total_value - total_cost),
        "items": items,
    }


# ── Profit & Loss ─────────────────────────────────────────────────

def get_profit_loss(tenant_id: str, year: int = None, month: int = None) -> dict:
    """Simplified P&L (Estado de Resultados) from accounting entries."""
    q = (
        db.session.query(
            ChartOfAccount.puc_code,
            ChartOfAccount.name,
            ChartOfAccount.account_type,
            ChartOfAccount.normal_balance,
            func.coalesce(func.sum(JournalLine.debit_amount), 0).label("debit"),
            func.coalesce(func.sum(JournalLine.credit_amount), 0).label("credit"),
        )
        .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(
            ChartOfAccount.tenant_id == tenant_id,
            ChartOfAccount.account_type.in_(["income", "expense", "cost"]),
        )
    )

    if year and month:
        # Accumulated P&L: January through selected month (NIIF standard)
        q = q.join(
            AccountingPeriod, JournalEntry.period_id == AccountingPeriod.id
        ).filter(AccountingPeriod.year == year, AccountingPeriod.month <= month)
    elif year:
        q = q.join(
            AccountingPeriod, JournalEntry.period_id == AccountingPeriod.id
        ).filter(AccountingPeriod.year == year)

    q = q.group_by(
        ChartOfAccount.puc_code, ChartOfAccount.name,
        ChartOfAccount.account_type, ChartOfAccount.normal_balance,
    ).order_by(ChartOfAccount.puc_code)

    rows = q.all()

    income_total = Decimal("0")
    cost_total = Decimal("0")
    expense_total = Decimal("0")

    income_items = []
    cost_items = []
    expense_items = []

    for r in rows:
        d = Decimal(str(r.debit))
        c = Decimal(str(r.credit))
        balance = c - d if r.normal_balance == "credit" else d - c

        item = {"puc_code": r.puc_code, "name": r.name, "balance": float(abs(balance))}

        if r.account_type == "income":
            income_total += abs(balance)
            income_items.append(item)
        elif r.account_type == "cost":
            cost_total += abs(balance)
            cost_items.append(item)
        elif r.account_type == "expense":
            expense_total += abs(balance)
            expense_items.append(item)

    gross_profit = income_total - cost_total
    net_profit = gross_profit - expense_total

    return {
        "period": f"{year}-{month:02d}" if year and month else "all",
        "income": {"total": float(income_total), "items": income_items},
        "cost_of_sales": {"total": float(cost_total), "items": cost_items},
        "gross_profit": float(gross_profit),
        "expenses": {"total": float(expense_total), "items": expense_items},
        "net_profit": float(net_profit),
        "gross_margin_pct": round(float(gross_profit / income_total * 100), 2) if income_total > 0 else 0,
        "net_margin_pct": round(float(net_profit / income_total * 100), 2) if income_total > 0 else 0,
    }


# ── DIAN Support Reports ──────────────────────────────────────────

def get_dian_iva_report(tenant_id: str, year: int, month: int) -> dict:
    """IVA summary: generated vs deductible = net payable."""
    from app.modules.accounting.models import (
        AccountingPeriod, ChartOfAccount, JournalEntry, JournalLine,
    )

    # IVA generated (2408 — credit account)
    iva_gen = (
        db.session.query(
            func.coalesce(func.sum(JournalLine.credit_amount), 0).label("credit"),
            func.coalesce(func.sum(JournalLine.debit_amount), 0).label("debit"),
        )
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .join(ChartOfAccount, JournalLine.account_id == ChartOfAccount.id)
        .join(AccountingPeriod, JournalEntry.period_id == AccountingPeriod.id)
        .filter(
            ChartOfAccount.tenant_id == tenant_id,
            ChartOfAccount.puc_code == "2408",
            AccountingPeriod.year == year,
            AccountingPeriod.month == month,
        )
        .first()
    )

    # IVA deductible = debits of 2408 (purchases reduce IVA payable)
    # Both generated and deductible are in the same account 2408
    # Generated = credits (from sales), Deductible = debits (from purchases)
    generated = float((iva_gen.credit or 0))
    deductible = float((iva_gen.debit or 0))
    net_payable = generated - deductible

    # Sales and purchases totals
    sales_total = (
        db.session.query(
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.subtotal), 0).label("base"),
            func.coalesce(func.sum(Sale.tax_amount), 0).label("tax"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total"),
        )
        .filter(
            Sale.tenant_id == tenant_id,
            Sale.status == "completed",
            func.extract("year", Sale.sale_date) == year,
            func.extract("month", Sale.sale_date) == month,
        )
        .first()
    )

    purchases_total = (
        db.session.query(
            func.count(PurchaseOrder.id).label("count"),
            func.coalesce(func.sum(PurchaseOrder.subtotal), 0).label("base"),
            func.coalesce(func.sum(PurchaseOrder.tax_amount), 0).label("tax"),
            func.coalesce(func.sum(PurchaseOrder.total_amount), 0).label("total"),
        )
        .filter(
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.status == "received",
            func.extract("year", PurchaseOrder.received_at) == year,
            func.extract("month", PurchaseOrder.received_at) == month,
        )
        .first()
    )

    return {
        "period": f"{year}-{month:02d}",
        "iva_generated": generated,
        "iva_deductible": deductible,
        "iva_net_payable": net_payable,
        "iva_balance": "a_pagar" if net_payable > 0 else "a_favor",
        "sales": {
            "count": sales_total.count or 0,
            "taxable_base": float(sales_total.base or 0),
            "iva": float(sales_total.tax or 0),
            "total": float(sales_total.total or 0),
        },
        "purchases": {
            "count": purchases_total.count or 0,
            "taxable_base": float(purchases_total.base or 0),
            "iva": float(purchases_total.tax or 0),
            "total": float(purchases_total.total or 0),
        },
    }


# ── CSV Export Helpers ────────────────────────────────────────────

def export_trial_balance_csv(tenant_id: str, year: int = None, month: int = None) -> str:
    """Export trial balance as CSV string."""
    import csv
    import io

    data = get_trial_balance(tenant_id, year, month)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Cuenta PUC", "Nombre", "Tipo", "Débito", "Crédito", "Saldo"])
    for a in data["accounts"]:
        writer.writerow([a["puc_code"], a["name"], a["account_type"],
                         a["total_debit"], a["total_credit"], a["balance"]])
    writer.writerow([])
    writer.writerow(["TOTALES", "", "", data["total_debit"], data["total_credit"],
                     "Cuadrado" if data["is_balanced"] else "DESCUADRE"])
    return output.getvalue()


def export_profit_loss_csv(tenant_id: str, year: int = None, month: int = None) -> str:
    """Export P&L as CSV string."""
    import csv
    import io

    data = get_profit_loss(tenant_id, year, month)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Estado de Resultados", f"Periodo: {data['period']}"])
    writer.writerow([])
    writer.writerow(["Concepto", "Código PUC", "Valor"])
    writer.writerow(["INGRESOS", "", data["income"]["total"]])
    for i in data["income"]["items"]:
        writer.writerow([f"  {i['name']}", i["puc_code"], i["balance"]])
    writer.writerow(["COSTO DE VENTAS", "", data["cost_of_sales"]["total"]])
    for i in data["cost_of_sales"]["items"]:
        writer.writerow([f"  {i['name']}", i["puc_code"], i["balance"]])
    writer.writerow(["UTILIDAD BRUTA", "", data["gross_profit"]])
    writer.writerow(["GASTOS", "", data["expenses"]["total"]])
    for i in data["expenses"]["items"]:
        writer.writerow([f"  {i['name']}", i["puc_code"], i["balance"]])
    writer.writerow(["UTILIDAD NETA", "", data["net_profit"]])
    writer.writerow([f"Margen bruto: {data['gross_margin_pct']}%"])
    writer.writerow([f"Margen neto: {data['net_margin_pct']}%"])
    return output.getvalue()


def export_inventory_csv(tenant_id: str) -> str:
    """Export inventory report as CSV string."""
    import csv
    import io

    data = get_inventory_report(tenant_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Producto", "SKU", "Stock", "Mínimo", "Unidad",
                     "Precio Venta", "Costo Promedio", "Valor Costo", "Valor Venta", "Estado"])
    for i in data["items"]:
        writer.writerow([i["name"], i["sku"], i["stock"], i["minimum"], i["unit"],
                         i["sale_price"], i["cost_average"], i["value_at_cost"],
                         i["value_at_sale"], "BAJO" if i["is_low_stock"] else "OK"])
    writer.writerow([])
    writer.writerow(["TOTALES", "", "", "", "", "", "",
                     data["total_value_at_cost"], data["total_value_at_sale"]])
    return output.getvalue()


# ── Sales by Product Report ───────────────────────────────────────

def get_sales_by_product(tenant_id: str, date_from: str = None, date_to: str = None) -> list:
    """Sales breakdown by product for a date range."""
    if not date_from:
        date_from = _today_bogota()
    if not date_to:
        date_to = _today_bogota()

    rows = (
        db.session.query(
            SaleItem.product_name,
            SaleItem.product_id,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.subtotal).label("revenue"),
            func.sum(SaleItem.tax_amount).label("tax"),
            func.sum(SaleItem.total).label("total"),
            func.count(func.distinct(Sale.id)).label("num_sales"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.tenant_id == tenant_id,
            Sale.status == "completed",
            _date_in_bogota(Sale.sale_date) >= date_from,
            _date_in_bogota(Sale.sale_date) <= date_to,
        )
        .group_by(SaleItem.product_name, SaleItem.product_id)
        .order_by(desc("total"))
        .all()
    )

    return [
        {
            "product_name": r.product_name,
            "product_id": str(r.product_id),
            "quantity_sold": float(r.qty),
            "revenue": float(r.revenue),
            "tax": float(r.tax),
            "total": float(r.total),
            "num_sales": r.num_sales,
        }
        for r in rows
    ]


def export_sales_by_product_csv(data: list) -> str:
    """Export sales by product as CSV."""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Producto", "Cantidad Vendida", "Subtotal", "IVA", "Total", "# Ventas"])
    for r in data:
        writer.writerow([r["product_name"], r["quantity_sold"], r["revenue"],
                         r["tax"], r["total"], r["num_sales"]])
    return output.getvalue()


# ── Stock Alerts ──────────────────────────────────────────────────

def get_stock_alerts(tenant_id: str) -> list:
    """Products with stock at or below minimum."""
    products = (
        Product.query.filter(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.deleted_at.is_(None),
            Product.stock_current <= Product.stock_minimum,
        )
        .order_by(Product.stock_current)
        .all()
    )

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "sku": p.sku,
            "stock_current": float(p.stock_current),
            "stock_minimum": float(p.stock_minimum),
            "deficit": float(p.stock_minimum - p.stock_current),
            "cost_to_restock": float((p.stock_minimum - p.stock_current) * p.cost_average)
                if p.stock_current < p.stock_minimum else 0,
        }
        for p in products
    ]


# ── Transactions Report ──────────────────────────────────────────

def get_transactions(
    tenant_id: str, page: int = 1, per_page: int = 50,
    date_from: str = None, date_to: str = None,
) -> dict:
    """All sales transactions with detail."""
    q = Sale.query.filter(Sale.tenant_id == tenant_id)

    if date_from:
        q = q.filter(_date_in_bogota(Sale.sale_date) >= date_from)
    if date_to:
        q = q.filter(_date_in_bogota(Sale.sale_date) <= date_to)

    total = q.count()
    sales = q.order_by(Sale.sale_date.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return {
        "data": [
            {
                "id": str(s.id),
                "invoice_number": s.invoice_number,
                "date": s.sale_date.isoformat(),
                "status": s.status,
                "subtotal": float(s.subtotal),
                "tax": float(s.tax_amount),
                "total": float(s.total_amount),
                "items_count": len(s.items),
                "payment_method": s.payments[0].method if s.payments else None,
                "items": [
                    {"name": i.product_name, "qty": float(i.quantity),
                     "price": float(i.unit_price), "total": float(i.total)}
                    for i in s.items
                ],
            }
            for s in sales
        ],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "has_next": page * per_page < total,
        },
    }


# ── Annual Tax Summary (Renta) ────────────────────────────────────

def get_annual_tax_summary(tenant_id: str, year: int) -> dict:
    """Annual fiscal summary for Colombian income tax declaration (renta)."""
    from app.modules.accounting.models import ChartOfAccount, JournalEntry, JournalLine, AccountingPeriod

    def _sum_accounts(puc_codes: list, yr: int) -> Decimal:
        """Sum balance for given PUC codes in a year."""
        result = (
            db.session.query(
                func.coalesce(func.sum(JournalLine.debit_amount), 0).label("d"),
                func.coalesce(func.sum(JournalLine.credit_amount), 0).label("c"),
            )
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .join(ChartOfAccount, JournalLine.account_id == ChartOfAccount.id)
            .join(AccountingPeriod, JournalEntry.period_id == AccountingPeriod.id)
            .filter(
                ChartOfAccount.tenant_id == tenant_id,
                ChartOfAccount.puc_code.in_(puc_codes),
                AccountingPeriod.year == yr,
            )
            .first()
        )
        return Decimal(str(result.d or 0)), Decimal(str(result.c or 0))

    # INGRESOS (clase 4 — naturaleza crédito)
    d, c = _sum_accounts(["4135"], year)
    ingresos_brutos = c - d
    d2, c2 = _sum_accounts(["4175"], year)
    devoluciones_ventas = d2 - c2
    ingresos_netos = ingresos_brutos - devoluciones_ventas

    # COSTOS (clase 6 — naturaleza débito)
    d, c = _sum_accounts(["6135"], year)
    costo_ventas = d - c

    # GASTOS (clase 5)
    gastos_codes = ["5105", "5135", "5195", "5305"]
    d, c = _sum_accounts(gastos_codes, year)
    gastos_operacionales = d - c

    renta_liquida = ingresos_netos - costo_ventas - gastos_operacionales

    # PATRIMONIO — saldos acumulados (all-time, no solo el año)
    def _balance_all(puc_codes: list) -> Decimal:
        result = (
            db.session.query(
                func.coalesce(func.sum(JournalLine.debit_amount), 0).label("d"),
                func.coalesce(func.sum(JournalLine.credit_amount), 0).label("c"),
            )
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .join(ChartOfAccount, JournalLine.account_id == ChartOfAccount.id)
            .filter(
                ChartOfAccount.tenant_id == tenant_id,
                ChartOfAccount.puc_code.in_(puc_codes),
            )
            .first()
        )
        return Decimal(str(result.d or 0)), Decimal(str(result.c or 0))

    # Activos (naturaleza débito) — include all class 1 accounts
    d, c = _balance_all(["1105", "1110", "1115", "1120", "1305", "1330", "1380", "1435", "1520", "1705"])
    activos = abs(d - c)

    # Pasivos (naturaleza crédito) — include all class 2 accounts
    d, c = _balance_all(["2105", "2205", "2335", "2365", "2366", "2368", "2370", "2408", "2505", "2510"])
    pasivos = abs(c - d)

    patrimonio_liquido = activos - pasivos

    # IVA del año
    d_gen, c_gen = _sum_accounts(["2408"], year)
    iva_generado = c_gen - d_gen
    # IVA descontable = debits of 2408 (from purchases)
    iva_descontable = d_gen  # debits of 2408 are the deductible IVA
    iva_neto = iva_generado - iva_descontable

    # Sales and purchases counts
    sales_count = Sale.query.filter(
        Sale.tenant_id == tenant_id, Sale.status == "completed",
        func.extract("year", Sale.sale_date) == year,
    ).count()

    return {
        "year": year,
        "ingresos": {
            "brutos": float(ingresos_brutos),
            "devoluciones": float(devoluciones_ventas),
            "netos": float(ingresos_netos),
        },
        "costos": {"ventas": float(costo_ventas)},
        "gastos": {"operacionales": float(gastos_operacionales)},
        "renta_liquida": float(renta_liquida),
        "patrimonio": {
            "activos": float(activos),
            "pasivos": float(pasivos),
            "liquido": float(patrimonio_liquido),
        },
        "iva": {
            "generado": float(iva_generado),
            "descontable": float(iva_descontable),
            "neto": float(iva_neto),
            "balance": "a_pagar" if iva_neto > 0 else "a_favor",
        },
        "operaciones": {"ventas_realizadas": sales_count},
    }


def export_tax_summary_csv(data: dict) -> str:
    """Export annual tax summary as CSV."""
    import csv
    import io
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["RESUMEN FISCAL ANUAL", data["year"]])
    w.writerow([])
    w.writerow(["INGRESOS FISCALES"])
    w.writerow(["Ingresos brutos operacionales", data["ingresos"]["brutos"]])
    w.writerow(["(-) Devoluciones en ventas", data["ingresos"]["devoluciones"]])
    w.writerow(["= Ingresos netos", data["ingresos"]["netos"]])
    w.writerow([])
    w.writerow(["COSTOS Y DEDUCCIONES"])
    w.writerow(["Costo de ventas", data["costos"]["ventas"]])
    w.writerow(["Gastos operacionales", data["gastos"]["operacionales"]])
    w.writerow([])
    w.writerow(["RENTA LIQUIDA", data["renta_liquida"]])
    w.writerow([])
    w.writerow(["PATRIMONIO AL 31-DIC"])
    w.writerow(["Activos (efectivo+cartera+inventario)", data["patrimonio"]["activos"]])
    w.writerow(["Pasivos (proveedores+impuestos)", data["patrimonio"]["pasivos"]])
    w.writerow(["= Patrimonio liquido", data["patrimonio"]["liquido"]])
    w.writerow([])
    w.writerow(["IVA ANUAL"])
    w.writerow(["IVA generado", data["iva"]["generado"]])
    w.writerow(["IVA descontable", data["iva"]["descontable"]])
    w.writerow(["IVA neto", data["iva"]["neto"]])
    return output.getvalue()


# ── Analytics Reports ────────────────────────────────────────────

def get_product_margins(tenant_id: str, date_from: str = None, date_to: str = None) -> list:
    """Top products by gross margin percentage."""
    q = (
        db.session.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.subtotal).label("revenue"),
            func.sum(SaleItem.quantity * SaleItem.unit_cost).label("cost"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.tenant_id == tenant_id, Sale.status == "completed")
    )
    if date_from:
        q = q.filter(_date_in_bogota(Sale.sale_date) >= date_from)
    if date_to:
        q = q.filter(_date_in_bogota(Sale.sale_date) <= date_to)

    rows = q.group_by(SaleItem.product_name).order_by(desc("revenue")).limit(15).all()

    return [{
        "name": r.product_name,
        "qty": float(r.qty),
        "revenue": float(r.revenue),
        "cost": float(r.cost),
        "margin": float(r.revenue) - float(r.cost),
        "margin_pct": round((float(r.revenue) - float(r.cost)) / max(float(r.revenue), 0.01) * 100, 1),
    } for r in rows]


def get_expenses_trend(tenant_id: str, months: int = 6) -> list:
    """Monthly expenses grouped by PUC code (top categories)."""
    from app.modules.accounting.models import Expense
    from datetime import datetime
    import calendar

    now = datetime.now(BOGOTA_TZ)
    results = []

    for i in range(months - 1, -1, -1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1

        month_expenses = (
            db.session.query(
                Expense.puc_code,
                func.sum(Expense.amount).label("total"),
            )
            .filter(
                Expense.tenant_id == tenant_id,
                Expense.status == "active",
                func.extract("year", Expense.expense_date) == y,
                func.extract("month", Expense.expense_date) == m,
            )
            .group_by(Expense.puc_code)
            .all()
        )

        # Also get expenses from journal entries for expense accounts (class 5)
        je_expenses = (
            db.session.query(
                ChartOfAccount.puc_code,
                ChartOfAccount.name,
                func.sum(JournalLine.debit_amount).label("total"),
            )
            .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .join(AccountingPeriod, JournalEntry.period_id == AccountingPeriod.id)
            .filter(
                ChartOfAccount.tenant_id == tenant_id,
                ChartOfAccount.account_type == "expense",
                AccountingPeriod.year == y,
                AccountingPeriod.month == m,
                JournalLine.debit_amount > 0,
            )
            .group_by(ChartOfAccount.puc_code, ChartOfAccount.name)
            .all()
        )

        period_data = {"period": f"{y}-{m:02d}", "categories": {}}
        for row in je_expenses:
            period_data["categories"][row.name] = float(row.total)

        results.append(period_data)

    return results


def get_profit_trend(tenant_id: str, period: str = "daily", days: int = 30) -> list:
    """Profit trend: revenue, cost, and gross profit by day/week/month. Optimized: 3 queries total."""
    now = datetime.now(BOGOTA_TZ)
    start = now - timedelta(days=days)

    if period == "monthly":
        trunc = func.date_trunc("month", func.timezone("America/Bogota", Sale.sale_date))
        cn_trunc = func.date_trunc("month", func.timezone("America/Bogota", CreditNote.created_at))
    else:
        trunc = func.date_trunc("day", func.timezone("America/Bogota", Sale.sale_date))
        cn_trunc = func.date_trunc("day", func.timezone("America/Bogota", CreditNote.created_at))

    # Query 1: revenue + cost grouped by period (1 query instead of N×2)
    sales_data = db.session.query(
        trunc.label("period"),
        func.coalesce(func.sum(Sale.subtotal), 0).label("revenue"),
    ).filter(
        Sale.tenant_id == tenant_id, Sale.status == "completed",
        Sale.sale_date >= start,
    ).group_by("period").all()

    cost_data = db.session.query(
        trunc.label("period"),
        func.coalesce(func.sum(SaleItem.quantity * SaleItem.unit_cost), 0).label("cost"),
    ).join(Sale).filter(
        Sale.tenant_id == tenant_id, Sale.status == "completed",
        Sale.sale_date >= start,
    ).group_by("period").all()

    # Query 2: credit notes grouped by period
    cn_data = db.session.query(
        cn_trunc.label("period"),
        func.coalesce(func.sum(CreditNote.subtotal), 0).label("cn_total"),
    ).filter(
        CreditNote.tenant_id == tenant_id,
        CreditNote.created_at >= start,
    ).group_by("period").all()

    # Merge into dict by period key
    rev_map = {r.period.strftime("%Y-%m-%d" if period != "monthly" else "%Y-%m"): float(r.revenue) for r in sales_data}
    cost_map = {r.period.strftime("%Y-%m-%d" if period != "monthly" else "%Y-%m"): float(r.cost) for r in cost_data}
    cn_map = {r.period.strftime("%Y-%m-%d" if period != "monthly" else "%Y-%m"): float(r.cn_total) for r in cn_data}

    # Build results with all days/months in range
    results = []
    if period == "monthly":
        for i in range(5, -1, -1):
            m = now.month - i
            y = now.year
            while m <= 0:
                m += 12; y -= 1
            key = f"{y}-{m:02d}"
            rev = rev_map.get(key, 0) - cn_map.get(key, 0)
            cst = cost_map.get(key, 0)
            results.append({"period": key, "revenue": rev, "cost": cst,
                            "profit": round(rev - cst, 2),
                            "margin_pct": round((rev - cst) / max(rev, 0.01) * 100, 1)})
    else:
        for i in range(days - 1, -1, -1):
            key = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            rev = rev_map.get(key, 0) - cn_map.get(key, 0)
            cst = cost_map.get(key, 0)
            results.append({"period": key, "revenue": rev, "cost": cst,
                            "profit": round(rev - cst, 2),
                            "margin_pct": round((rev - cst) / max(rev, 0.01) * 100, 1)})

    total_rev = sum(r["revenue"] for r in results)
    total_cost = sum(r["cost"] for r in results)
    total_profit = sum(r["profit"] for r in results)

    return {
        "period_type": period,
        "data": results,
        "totals": {
            "revenue": total_rev, "cost": total_cost, "profit": total_profit,
            "margin_pct": round(total_profit / max(total_rev, 0.01) * 100, 1),
        }
    }


def get_cash_flow(tenant_id: str, days: int = 30) -> list:
    """Daily cash flow: inflows vs outflows. Optimized: 4 queries total (was 120)."""
    from app.modules.cash.models import CashReceipt, CashDisbursement

    now = datetime.now(BOGOTA_TZ)
    start = now - timedelta(days=days)
    day_trunc_cr = func.date_trunc("day", func.timezone("America/Bogota", CashReceipt.receipt_date))
    day_trunc_cd = func.date_trunc("day", func.timezone("America/Bogota", CashDisbursement.disbursement_date))
    day_trunc_sale = func.date_trunc("day", func.timezone("America/Bogota", Sale.sale_date))
    day_trunc_sp = func.date_trunc("day", func.timezone("America/Bogota", SupplierPayment.payment_date))

    # Inflows: cash receipts grouped by day
    cr_data = db.session.query(
        day_trunc_cr.label("day"), func.coalesce(func.sum(CashReceipt.amount), 0).label("total")
    ).filter(
        CashReceipt.tenant_id == tenant_id, CashReceipt.status == "active",
        CashReceipt.receipt_date >= start,
    ).group_by("day").all()

    # Inflows: sale cash payments grouped by day
    sp_data = db.session.query(
        day_trunc_sale.label("day"), func.coalesce(func.sum(Payment.amount), 0).label("total")
    ).join(Sale, Payment.sale_id == Sale.id).filter(
        Sale.tenant_id == tenant_id, Sale.status == "completed",
        Sale.sale_date >= start, Payment.method == "cash",
    ).group_by("day").all()

    # Outflows: cash disbursements grouped by day
    cd_data = db.session.query(
        day_trunc_cd.label("day"), func.coalesce(func.sum(CashDisbursement.amount), 0).label("total")
    ).filter(
        CashDisbursement.tenant_id == tenant_id, CashDisbursement.status == "active",
        CashDisbursement.disbursement_date >= start,
    ).group_by("day").all()

    # Outflows: supplier payments grouped by day
    sup_data = db.session.query(
        day_trunc_sp.label("day"), func.coalesce(func.sum(SupplierPayment.amount), 0).label("total")
    ).filter(
        SupplierPayment.tenant_id == tenant_id, SupplierPayment.status == "completed",
        SupplierPayment.payment_date >= start,
    ).group_by("day").all()

    # Merge into dicts
    fmt = lambda r: r.day.strftime("%Y-%m-%d")
    cr_map = {fmt(r): float(r.total) for r in cr_data}
    sp_map = {fmt(r): float(r.total) for r in sp_data}
    cd_map = {fmt(r): float(r.total) for r in cd_data}
    sup_map = {fmt(r): float(r.total) for r in sup_data}

    results = []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        total_in = cr_map.get(day, 0) + sp_map.get(day, 0)
        total_out = cd_map.get(day, 0) + sup_map.get(day, 0)
        results.append({"date": day, "inflows": total_in, "outflows": total_out, "net": total_in - total_out})

    return results


def get_receivables_vs_payables(tenant_id: str) -> dict:
    """CxC vs CxP comparison."""
    # CxC: outstanding credit sales
    cxc = db.session.query(
        func.coalesce(func.sum(Sale.amount_due), 0)
    ).filter(
        Sale.tenant_id == tenant_id,
        Sale.sale_type == "credit",
        Sale.status == "completed",
        Sale.payment_status.in_(["pending", "partial", "overdue"]),
    ).scalar()

    # CxP: use existing balance logic
    total_credit_purchases = db.session.query(
        func.coalesce(func.sum(PurchaseOrder.total_amount), 0)
    ).filter(
        PurchaseOrder.tenant_id == tenant_id,
        PurchaseOrder.payment_type == "credit",
        PurchaseOrder.status.in_(["received", "partially_received"]),
    ).scalar()

    total_supplier_payments = db.session.query(
        func.coalesce(func.sum(SupplierPayment.amount), 0)
    ).filter(
        SupplierPayment.tenant_id == tenant_id,
        SupplierPayment.status == "completed",
    ).scalar()

    cxp = float(total_credit_purchases) - float(total_supplier_payments)

    return {
        "cxc": float(cxc),
        "cxp": max(cxp, 0),
        "net_position": float(cxc) - max(cxp, 0),
    }


def get_inventory_rotation(tenant_id: str) -> dict:
    """Inventory rotation analysis: fast movers, slow movers, dead stock."""
    from datetime import timedelta as td

    now = datetime.now(BOGOTA_TZ)
    thirty_days_ago = (now - td(days=30)).strftime("%Y-%m-%d")

    # Products with sales in last 30 days
    fast_movers = (
        db.session.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.total).label("revenue"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.tenant_id == tenant_id,
            Sale.status == "completed",
            _date_in_bogota(Sale.sale_date) >= thirty_days_ago,
        )
        .group_by(SaleItem.product_name)
        .order_by(desc("qty"))
        .limit(10)
        .all()
    )

    # Products with NO movement in 30+ days
    products_with_recent = (
        db.session.query(StockMovement.product_id)
        .filter(
            StockMovement.tenant_id == tenant_id,
            _date_in_bogota(StockMovement.created_at) >= thirty_days_ago,
        )
        .distinct()
        .subquery()
    )

    dead_stock = (
        Product.query.filter(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.stock_current > 0,
            ~Product.id.in_(db.session.query(products_with_recent.c.product_id)),
        )
        .order_by(Product.stock_current.desc())
        .limit(10)
        .all()
    )

    return {
        "fast_movers": [{
            "name": r.product_name, "qty_sold": float(r.qty), "revenue": float(r.revenue)
        } for r in fast_movers],
        "dead_stock": [{
            "name": p.name, "stock": float(p.stock_current),
            "value": float(p.stock_current * p.cost_average),
        } for p in dead_stock],
        "dead_stock_total_value": sum(float(p.stock_current * p.cost_average) for p in dead_stock),
    }
