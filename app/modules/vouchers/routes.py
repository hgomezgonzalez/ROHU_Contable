"""Voucher routes — REST API endpoints."""

from flask import g, jsonify, request

from app.extensions import limiter
from app.modules.auth_rbac.services import require_permission
from app.modules.vouchers import services as voucher_svc
from app.modules.vouchers.blueprint import vouchers_bp
from app.modules.vouchers.exceptions import VoucherError
from app.modules.vouchers.schemas import (
    CancelVoucherSchema,
    CreateVoucherTypeSchema,
    EmitVoucherSchema,
    RedeemVoucherSchema,
    UpdateVoucherTypeSchema,
    ValidateVoucherSchema,
)


def _handle_voucher_error(e):
    """Map VoucherError to HTTP response."""
    status_map = {
        "VOUCHER_NOT_FOUND": 404,
        "VOUCHER_INVALID_CODE": 404,  # Same as not found to avoid info leak
        "VOUCHER_ALREADY_REDEEMED": 409,
        "VOUCHER_CONCURRENCY": 409,
        "VOUCHER_EXPIRED": 410,
        "VOUCHER_CANCELLED": 410,
        "VOUCHER_NOT_SOLD": 422,
        "VOUCHER_INSUFFICIENT_BALANCE": 422,
        "VOUCHER_TYPE_INACTIVE": 422,
        "VOUCHER_MAX_ISSUED": 422,
        "VOUCHER_PRINT_LIMIT": 422,
        "VOUCHER_HIGH_VALUE_REQUIRES_ID": 422,
    }
    status = status_map.get(e.code, 400)
    return jsonify(success=False, error={"code": e.code, "message": e.message}), status


# ── Voucher Types ────────────────────────────────────────────────


@vouchers_bp.route("/types", methods=["POST"])
@require_permission("vouchers", "manage")
def create_type():
    data = request.get_json() or {}
    errors = CreateVoucherTypeSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    try:
        result = voucher_svc.create_voucher_type(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            **CreateVoucherTypeSchema().load(data),
        )
        return jsonify(success=True, data=result), 201
    except (VoucherError, ValueError) as e:
        if isinstance(e, VoucherError):
            return _handle_voucher_error(e)
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": str(e)}), 400


@vouchers_bp.route("/types", methods=["GET"])
@require_permission("vouchers", "read")
def list_types():
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"
    result = voucher_svc.list_voucher_types(g.tenant_id, include_inactive)
    return jsonify(success=True, data=result)


@vouchers_bp.route("/types/<type_id>", methods=["PATCH"])
@require_permission("vouchers", "manage")
def update_type(type_id):
    data = request.get_json() or {}
    errors = UpdateVoucherTypeSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    try:
        result = voucher_svc.update_voucher_type(
            tenant_id=g.tenant_id,
            type_id=type_id,
            updated_by=str(g.current_user.id),
            **UpdateVoucherTypeSchema().load(data),
        )
        return jsonify(success=True, data=result)
    except (VoucherError, ValueError) as e:
        if isinstance(e, VoucherError):
            return _handle_voucher_error(e)
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": str(e)}), 400


@vouchers_bp.route("/types/<type_id>", methods=["DELETE"])
@require_permission("vouchers", "manage")
def delete_type(type_id):
    try:
        result = voucher_svc.delete_voucher_type(
            tenant_id=g.tenant_id,
            type_id=type_id,
            deleted_by=str(g.current_user.id),
        )
        return jsonify(success=True, data=result)
    except VoucherError as e:
        return _handle_voucher_error(e)


# ── Emission ─────────────────────────────────────────────────────


@vouchers_bp.route("/emit", methods=["POST"])
@require_permission("vouchers", "manage")
def emit():
    data = request.get_json() or {}
    errors = EmitVoucherSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    parsed = EmitVoucherSchema().load(data)

    try:
        quantity = parsed.pop("quantity", 1)
        if quantity == 1:
            result = voucher_svc.emit_voucher(
                tenant_id=g.tenant_id,
                type_id=str(parsed["type_id"]),
                created_by=str(g.current_user.id),
                idempotency_key=parsed.get("idempotency_key"),
            )
            return jsonify(success=True, data=result), 201
        else:
            results = voucher_svc.emit_batch(
                tenant_id=g.tenant_id,
                type_id=str(parsed["type_id"]),
                quantity=quantity,
                created_by=str(g.current_user.id),
            )
            return jsonify(success=True, data=results, count=len(results)), 201
    except (VoucherError, ValueError) as e:
        if isinstance(e, VoucherError):
            return _handle_voucher_error(e)
        return jsonify(success=False, error={"code": "EMISSION_ERROR", "message": str(e)}), 400


# ── Voucher Queries ──────────────────────────────────────────────


@vouchers_bp.route("/", methods=["GET"])
@require_permission("vouchers", "read")
def list_vouchers():
    result = voucher_svc.list_vouchers(
        tenant_id=g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
        status=request.args.get("status"),
        type_id=request.args.get("type_id"),
    )
    return jsonify(success=True, **result)


@vouchers_bp.route("/<voucher_id>", methods=["GET"])
@require_permission("vouchers", "read")
def get_voucher(voucher_id):
    result = voucher_svc.get_voucher(g.tenant_id, voucher_id)
    if not result:
        return jsonify(success=False, error={"code": "NOT_FOUND", "message": "Bono no encontrado"}), 404
    return jsonify(success=True, data=result)


@vouchers_bp.route("/by-code/<code>", methods=["GET"])
@require_permission("vouchers", "read")
def get_by_code(code):
    result = voucher_svc.get_voucher_by_code(g.tenant_id, code)
    if not result:
        return jsonify(success=False, error={"code": "NOT_FOUND", "message": "Bono no encontrado"}), 404
    return jsonify(success=True, data=result)


@vouchers_bp.route("/<voucher_id>/history", methods=["GET"])
@require_permission("vouchers", "read")
def get_history(voucher_id):
    result = voucher_svc.get_voucher_history(g.tenant_id, voucher_id)
    return jsonify(success=True, data=result)


# ── Validation & Redemption ──────────────────────────────────────


@vouchers_bp.route("/validate", methods=["POST"])
@require_permission("vouchers", "read")
@limiter.limit("20 per minute")
def validate():
    data = request.get_json() or {}
    errors = ValidateVoucherSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    try:
        result = voucher_svc.validate_voucher(g.tenant_id, data["code"])
        return jsonify(success=True, data=result)
    except VoucherError as e:
        return _handle_voucher_error(e)


@vouchers_bp.route("/redeem", methods=["POST"])
@require_permission("vouchers", "redeem")
@limiter.limit("10 per minute")
def redeem():
    data = request.get_json() or {}
    errors = RedeemVoucherSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    parsed = RedeemVoucherSchema().load(data)

    try:
        result = voucher_svc.redeem_voucher(
            tenant_id=g.tenant_id,
            code=parsed["code"],
            sale_id=str(parsed["sale_id"]),
            amount=parsed["amount"],
            cashier_id=str(g.current_user.id),
            idempotency_key=parsed["idempotency_key"],
            payment_id=str(parsed["payment_id"]) if parsed.get("payment_id") else None,
        )
        return jsonify(success=True, data=result)
    except VoucherError as e:
        return _handle_voucher_error(e)
    except ValueError as e:
        return jsonify(success=False, error={"code": "REDEMPTION_ERROR", "message": str(e)}), 400


# ── Cancellation ─────────────────────────────────────────────────


@vouchers_bp.route("/<voucher_id>/cancel", methods=["POST"])
@require_permission("vouchers", "manage")
def cancel(voucher_id):
    data = request.get_json() or {}
    errors = CancelVoucherSchema().validate(data)
    if errors:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": errors}), 400

    try:
        result = voucher_svc.cancel_voucher(
            tenant_id=g.tenant_id,
            voucher_id=voucher_id,
            cancelled_by=str(g.current_user.id),
            reason=data["reason"],
        )
        return jsonify(success=True, data=result)
    except (VoucherError, ValueError) as e:
        if isinstance(e, VoucherError):
            return _handle_voucher_error(e)
        return jsonify(success=False, error={"code": "CANCEL_ERROR", "message": str(e)}), 400


# ── Dashboard ────────────────────────────────────────────────────


@vouchers_bp.route("/stats", methods=["GET"])
@require_permission("vouchers", "read")
def stats():
    result = voucher_svc.get_voucher_stats(g.tenant_id)
    return jsonify(success=True, data=result)


# ── Print Tracking ───────────────────────────────────────────────


@vouchers_bp.route("/<voucher_id>/print", methods=["POST"])
@require_permission("vouchers", "manage")
def record_print(voucher_id):
    try:
        result = voucher_svc.record_print(
            tenant_id=g.tenant_id,
            voucher_id=voucher_id,
            printed_by=str(g.current_user.id),
        )
        return jsonify(success=True, data=result)
    except VoucherError as e:
        return _handle_voucher_error(e)


# ── Send Email ───────────────────────────────────────────────────


@vouchers_bp.route("/<voucher_id>/send-email", methods=["POST"])
@require_permission("vouchers", "manage")
def send_email(voucher_id):
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    if not email or "@" not in email:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "Email valido es requerido"}), 400

    try:
        result = voucher_svc.send_voucher_email(
            tenant_id=g.tenant_id,
            voucher_id=voucher_id,
            to_email=email,
            sent_by=str(g.current_user.id),
        )
        return jsonify(success=True, data=result)
    except VoucherError as e:
        return _handle_voucher_error(e)
    except Exception as e:
        return jsonify(success=False, error={"code": "EMAIL_ERROR", "message": str(e)}), 500
