"""Order routes — REST API endpoints."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.orders import services as order_svc
from app.modules.orders.blueprint import orders_bp
from app.modules.orders.exceptions import OrderError
from app.modules.orders.schemas import (
    CancelOrderSchema,
    CloseOrderSchema,
    CreateOrderSchema,
    UpdateOrderStateSchema,
)


def _handle_order_error(e):
    status_map = {
        "ORDER_NOT_FOUND": 404,
        "ORDER_STATE_ERROR": 409,
        "ORDER_CLOSE_STOCK_ERROR": 409,
        "ORDER_MAX_OPEN": 422,
        "ORDER_MODULE_DISABLED": 403,
    }
    status = status_map.get(e.code, 400)
    return jsonify(success=False, error={"code": e.code, "message": e.message}), status


# ── Create Order ─────────────────────────────────────────────────


@orders_bp.route("", methods=["POST"])
@require_permission("orders", "create")
def create_order():
    data = request.get_json() or {}
    errors = CreateOrderSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    parsed = CreateOrderSchema().load(data)
    try:
        result = order_svc.create_order(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            **parsed,
        )
        return jsonify(success=True, data=result), 201
    except (OrderError, ValueError) as e:
        if isinstance(e, OrderError):
            return _handle_order_error(e)
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": str(e)}), 400


# ── List Orders ──────────────────────────────────────────────────


@orders_bp.route("", methods=["GET"])
@require_permission("orders", "read")
def list_orders():
    result = order_svc.list_orders(
        tenant_id=g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
        status=request.args.get("status"),
        table_number=request.args.get("table"),
    )
    return jsonify(success=True, **result)


# ── Get Order ────────────────────────────────────────────────────


@orders_bp.route("/<order_id>", methods=["GET"])
@require_permission("orders", "read")
def get_order(order_id):
    result = order_svc.get_order(g.tenant_id, order_id)
    if not result:
        return jsonify(success=False, error={"code": "NOT_FOUND", "message": "Pedido no encontrado"}), 404
    return jsonify(success=True, data=result)


# ── Add Items ────────────────────────────────────────────────────


@orders_bp.route("/<order_id>/items", methods=["PATCH"])
@require_permission("orders", "create")
def add_items(order_id):
    data = request.get_json() or {}
    items = data.get("items", [])
    if not items:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "items es requerido"}), 400

    try:
        result = order_svc.add_items_to_order(
            order_id=order_id,
            tenant_id=g.tenant_id,
            items=items,
            added_by=str(g.current_user.id),
        )
        return jsonify(success=True, data=result)
    except (OrderError, ValueError) as e:
        if isinstance(e, OrderError):
            return _handle_order_error(e)
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": str(e)}), 400


# ── Confirm Order ────────────────────────────────────────────────


@orders_bp.route("/<order_id>/confirm", methods=["POST"])
@require_permission("orders", "update_status")
def confirm_order(order_id):
    try:
        result = order_svc.confirm_order(
            order_id=order_id,
            tenant_id=g.tenant_id,
            confirmed_by=str(g.current_user.id),
        )
        return jsonify(success=True, data=result)
    except (OrderError, ValueError) as e:
        if isinstance(e, OrderError):
            return _handle_order_error(e)
        return jsonify(success=False, error={"code": "CONFIRM_ERROR", "message": str(e)}), 400


# ── Update State ─────────────────────────────────────────────────


@orders_bp.route("/<order_id>/status", methods=["POST"])
@require_permission("orders", "update_status")
def update_status(order_id):
    data = request.get_json() or {}
    errors = UpdateOrderStateSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    parsed = UpdateOrderStateSchema().load(data)
    try:
        result = order_svc.update_order_state(
            order_id=order_id,
            tenant_id=g.tenant_id,
            new_status=parsed["status"],
            changed_by=str(g.current_user.id),
            reason=parsed.get("reason"),
        )
        return jsonify(success=True, data=result)
    except OrderError as e:
        return _handle_order_error(e)


# ── Close Order (creates Sale) ───────────────────────────────────


@orders_bp.route("/<order_id>/close", methods=["POST"])
@require_permission("orders", "close")
def close_order(order_id):
    data = request.get_json() or {}
    errors = CloseOrderSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    parsed = CloseOrderSchema().load(data)
    try:
        result = order_svc.close_order(
            order_id=order_id,
            tenant_id=g.tenant_id,
            closed_by=str(g.current_user.id),
            **parsed,
        )
        return jsonify(success=True, data=result)
    except (OrderError, ValueError) as e:
        if isinstance(e, OrderError):
            return _handle_order_error(e)
        return jsonify(success=False, error={"code": "CLOSE_ERROR", "message": str(e)}), 400


# ── Cancel Order ─────────────────────────────────────────────────


@orders_bp.route("/<order_id>/cancel", methods=["POST"])
@require_permission("orders", "cancel")
def cancel_order(order_id):
    data = request.get_json() or {}
    errors = CancelOrderSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    try:
        result = order_svc.cancel_order(
            order_id=order_id,
            tenant_id=g.tenant_id,
            cancelled_by=str(g.current_user.id),
            reason=data["reason"],
        )
        return jsonify(success=True, data=result)
    except (OrderError, ValueError) as e:
        if isinstance(e, OrderError):
            return _handle_order_error(e)
        return jsonify(success=False, error={"code": "CANCEL_ERROR", "message": str(e)}), 400


# ── KDS (Kitchen Display) ───────────────────────────────────────


@orders_bp.route("/kds", methods=["GET"])
@require_permission("orders", "read")
def kds_orders():
    result = order_svc.get_kds_orders(
        tenant_id=g.tenant_id,
        branch_id=request.args.get("branch_id"),
    )
    return jsonify(success=True, data=result)


# ── Stats ────────────────────────────────────────────────────────


@orders_bp.route("/stats", methods=["GET"])
@require_permission("orders", "read")
def stats():
    result = order_svc.get_order_stats(g.tenant_id)
    return jsonify(success=True, data=result)


# ── History ──────────────────────────────────────────────────────


@orders_bp.route("/<order_id>/history", methods=["GET"])
@require_permission("orders", "read")
def history(order_id):
    result = order_svc.get_order_history(g.tenant_id, order_id)
    return jsonify(success=True, data=result)
