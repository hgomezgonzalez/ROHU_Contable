"""POS routes — REST API endpoints."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.pos.blueprint import pos_bp
from app.modules.pos import services as pos


# ── Cash Sessions ─────────────────────────────────────────────────

@pos_bp.route("/cash-sessions/open", methods=["POST"])
@require_permission("cash_sessions", "manage")
def open_session():
    data = request.get_json() or {}
    try:
        session = pos.open_cash_session(
            tenant_id=g.tenant_id,
            user_id=str(g.current_user.id),
            opening_amount=data.get("opening_amount", 0),
        )
        return jsonify(success=True, data=session), 201
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "CASH_SESSION_ERROR", "message": str(e)
        }), 409


@pos_bp.route("/cash-sessions/close", methods=["POST"])
@require_permission("cash_sessions", "manage")
def close_session():
    data = request.get_json()
    if data.get("closing_amount") is None:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "closing_amount es requerido"
        }), 400

    try:
        session = pos.close_cash_session(
            tenant_id=g.tenant_id,
            user_id=str(g.current_user.id),
            closing_amount=data["closing_amount"],
            notes=data.get("notes", ""),
        )
        return jsonify(success=True, data=session)
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "CASH_SESSION_ERROR", "message": str(e)
        }), 409


@pos_bp.route("/cash-sessions/current", methods=["GET"])
@require_permission("sales", "read")
def current_session():
    session = pos.get_current_session(g.tenant_id)
    if not session:
        return jsonify(success=False, error={
            "code": "NO_OPEN_SESSION", "message": "No hay caja abierta"
        }), 404
    return jsonify(success=True, data=session)


# ── Checkout (Critical Path) ──────────────────────────────────────

@pos_bp.route("/checkout", methods=["POST"])
@require_permission("sales", "create")
def checkout():
    data = request.get_json()

    if not data.get("items"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "items es requerido"
        }), 400

    sale_type = data.get("sale_type", "cash")
    if sale_type == "cash" and not data.get("payments"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "payments es requerido para ventas de contado"
        }), 400

    try:
        sale = pos.checkout(
            tenant_id=g.tenant_id,
            cashier_id=str(g.current_user.id),
            items=data["items"],
            payments=data.get("payments", []),
            customer_name=data.get("customer_name"),
            customer_tax_id=data.get("customer_tax_id"),
            notes=data.get("notes"),
            idempotency_key=data.get("idempotency_key"),
            cash_session_id=data.get("cash_session_id"),
            sale_type=sale_type,
            customer_id=data.get("customer_id"),
            credit_days=data.get("credit_days", 0),
        )
        return jsonify(success=True, data=sale), 201
    except ValueError as e:
        code = "INSUFFICIENT_STOCK" if "Stock insuficiente" in str(e) else "CHECKOUT_ERROR"
        return jsonify(success=False, error={
            "code": code, "message": str(e)
        }), 409


# ── Sales ─────────────────────────────────────────────────────────

@pos_bp.route("/sales", methods=["GET"])
@require_permission("sales", "read")
def list_sales():
    result = pos.list_sales(
        tenant_id=g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
        status=request.args.get("status"),
        cashier_id=request.args.get("cashier_id"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(success=True, **result)


@pos_bp.route("/sales/<sale_id>", methods=["GET"])
@require_permission("sales", "read")
def get_sale(sale_id):
    sale = pos.get_sale(g.tenant_id, sale_id)
    if not sale:
        return jsonify(success=False, error={
            "code": "SALE_NOT_FOUND", "message": "Venta no encontrada"
        }), 404
    return jsonify(success=True, data=sale)


@pos_bp.route("/sales/<sale_id>/void", methods=["POST"])
@require_permission("sales", "void")
def void_sale(sale_id):
    data = request.get_json() or {}
    reason = data.get("reason", "")
    if not reason:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "reason es requerido"
        }), 400

    try:
        sale = pos.void_sale(
            tenant_id=g.tenant_id,
            sale_id=sale_id,
            user_id=str(g.current_user.id),
            reason=reason,
        )
        return jsonify(success=True, data=sale)
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "VOID_ERROR", "message": str(e)
        }), 409


@pos_bp.route("/sales/<sale_id>/return", methods=["POST"])
@require_permission("sales", "void")
def return_sale(sale_id):
    data = request.get_json()
    if not data.get("items") or not data.get("reason"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR",
            "message": "items y reason son requeridos. items: [{product_id, quantity}]"
        }), 400

    try:
        cn = pos.create_return(
            tenant_id=g.tenant_id, sale_id=sale_id,
            user_id=str(g.current_user.id),
            items=data["items"], reason=data["reason"],
        )
        return jsonify(success=True, data=cn), 201
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "RETURN_ERROR", "message": str(e)
        }), 409


# ── Dashboard ─────────────────────────────────────────────────────

@pos_bp.route("/daily-totals", methods=["GET"])
@require_permission("sales", "read")
def daily_totals():
    date = request.args.get("date")
    totals = pos.get_daily_totals(g.tenant_id, date)
    return jsonify(success=True, data=totals)
