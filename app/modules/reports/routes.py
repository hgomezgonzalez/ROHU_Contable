"""Reports routes — Dashboard, sales, inventory, P&L, DIAN, exports."""

from flask import g, jsonify, request, Response

from app.modules.auth_rbac.services import require_permission
from app.modules.reports.blueprint import reports_bp
from app.modules.reports import services as rpt


@reports_bp.route("/dashboard", methods=["GET"])
@require_permission("reports", "read")
def dashboard():
    date = request.args.get("date")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    data = rpt.get_dashboard(g.tenant_id, date=date, date_from=date_from, date_to=date_to)
    return jsonify(success=True, data=data)


@reports_bp.route("/sales", methods=["GET"])
@require_permission("reports", "read")
def sales_report():
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    if not date_from or not date_to:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR",
            "message": "date_from y date_to son requeridos (YYYY-MM-DD)"
        }), 400

    data = rpt.get_sales_report(
        tenant_id=g.tenant_id,
        date_from=date_from, date_to=date_to,
        group_by=request.args.get("group_by", "day"),
    )
    return jsonify(success=True, data=data)


@reports_bp.route("/inventory", methods=["GET"])
@require_permission("reports", "read")
def inventory_report():
    fmt = request.args.get("format")
    if fmt == "csv":
        csv_data = rpt.export_inventory_csv(g.tenant_id)
        return Response(csv_data, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=inventario_rohu.csv"})
    data = rpt.get_inventory_report(g.tenant_id)
    return jsonify(success=True, data=data)


@reports_bp.route("/profit-loss", methods=["GET"])
@require_permission("reports", "read")
def profit_loss():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    fmt = request.args.get("format")
    if fmt == "csv":
        csv_data = rpt.export_profit_loss_csv(g.tenant_id, year, month)
        return Response(csv_data, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=estado_resultados_rohu.csv"})
    data = rpt.get_profit_loss(g.tenant_id, year, month)
    return jsonify(success=True, data=data)


@reports_bp.route("/balance-sheet", methods=["GET"])
@require_permission("reports", "read")
def balance_sheet():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    data = rpt.get_balance_sheet(g.tenant_id, year, month)
    return jsonify(success=True, data=data)


# ── DIAN Support ──────────────────────────────────────────────────

@reports_bp.route("/dian/iva", methods=["GET"])
@require_permission("reports", "read")
def dian_iva():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    if not year or not month:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR",
            "message": "year y month son requeridos"
        }), 400

    data = rpt.get_dian_iva_report(g.tenant_id, year, month)
    return jsonify(success=True, data=data)


# ── CSV Exports ───────────────────────────────────────────────────

@reports_bp.route("/trial-balance/export", methods=["GET"])
@require_permission("reports", "export")
def export_trial_balance():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    csv_data = rpt.export_trial_balance_csv(g.tenant_id, year, month)
    return Response(csv_data, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=balance_prueba_rohu.csv"})


@reports_bp.route("/sales-by-product", methods=["GET"])
@require_permission("reports", "read")
def sales_by_product():
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    data = rpt.get_sales_by_product(g.tenant_id, date_from, date_to)
    fmt = request.args.get("format")
    if fmt == "csv":
        csv_data = rpt.export_sales_by_product_csv(data)
        return Response(csv_data, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=ventas_por_producto.csv"})
    return jsonify(success=True, data=data)


@reports_bp.route("/stock-alerts", methods=["GET"])
@require_permission("reports", "read")
def stock_alerts():
    data = rpt.get_stock_alerts(g.tenant_id)
    return jsonify(success=True, data=data)


@reports_bp.route("/tax-summary", methods=["GET"])
@require_permission("reports", "read")
def tax_summary():
    year = request.args.get("year", type=int)
    if not year:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        year = datetime.now(ZoneInfo("America/Bogota")).year

    fmt = request.args.get("format")
    data = rpt.get_annual_tax_summary(g.tenant_id, year)
    if fmt == "csv":
        csv_data = rpt.export_tax_summary_csv(data)
        return Response(csv_data, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=resumen_fiscal_{year}.csv"})
    return jsonify(success=True, data=data)


@reports_bp.route("/transactions", methods=["GET"])
@require_permission("reports", "read")
def transactions():
    data = rpt.get_transactions(
        tenant_id=g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 50)),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(success=True, **data)


@reports_bp.route("/health-summary", methods=["GET"])
@require_permission("reports", "read")
def health_summary():
    data = rpt.get_health_summary(g.tenant_id)
    return jsonify(success=True, data=data)


# ── Audit Log ────────────────────────────────────────────────────

@reports_bp.route("/audit-log", methods=["GET"])
@require_permission("audit_logs", "read")
def audit_log():
    from app.core.audit import AuditLog
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 100)
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    user_id = request.args.get("user_id")
    action = request.args.get("action")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    q = AuditLog.query.filter_by(tenant_id=g.tenant_id)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(AuditLog.entity_id == entity_id)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if date_from:
        q = q.filter(AuditLog.created_at >= date_from)
    if date_to:
        q = q.filter(AuditLog.created_at <= date_to)

    q = q.order_by(AuditLog.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    items = [{
        "id": str(log.id),
        "user_id": str(log.user_id) if log.user_id else None,
        "action": log.action,
        "entity_type": log.entity_type,
        "entity_id": str(log.entity_id),
        "changes": log.changes,
        "ip_address": log.ip_address,
        "created_at": log.created_at.isoformat(),
    } for log in pagination.items]

    return jsonify(
        success=True,
        data=items,
        page=pagination.page,
        total_pages=pagination.pages,
        total_items=pagination.total,
    )


# ── Analytics ────────────────────────────────────────────────────

@reports_bp.route("/analytics/margins", methods=["GET"])
@require_permission("reports", "read")
def product_margins():
    data = rpt.get_product_margins(
        g.tenant_id,
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(success=True, data=data)


@reports_bp.route("/analytics/expenses-trend", methods=["GET"])
@require_permission("reports", "read")
def expenses_trend():
    months = int(request.args.get("months", 6))
    data = rpt.get_expenses_trend(g.tenant_id, months=months)
    return jsonify(success=True, data=data)


@reports_bp.route("/analytics/profit-trend", methods=["GET"])
@require_permission("reports", "read")
def profit_trend():
    period = request.args.get("period", "daily")
    days = int(request.args.get("days", 30))
    data = rpt.get_profit_trend(g.tenant_id, period=period, days=days)
    return jsonify(success=True, data=data)


@reports_bp.route("/analytics/cash-flow", methods=["GET"])
@require_permission("reports", "read")
def cash_flow():
    days = int(request.args.get("days", 30))
    data = rpt.get_cash_flow(g.tenant_id, days=days)
    return jsonify(success=True, data=data)


@reports_bp.route("/analytics/receivables-payables", methods=["GET"])
@require_permission("reports", "read")
def receivables_payables():
    data = rpt.get_receivables_vs_payables(g.tenant_id)
    return jsonify(success=True, data=data)


@reports_bp.route("/analytics/inventory-rotation", methods=["GET"])
@require_permission("reports", "read")
def inventory_rotation():
    data = rpt.get_inventory_rotation(g.tenant_id)
    return jsonify(success=True, data=data)
