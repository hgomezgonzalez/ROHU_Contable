"""Cash routes — Receipts, Disbursements, Transfers."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.cash import services as cash
from app.modules.cash.blueprint import cash_bp

# ── Cash Receipts ────────────────────────────────────────────────


@cash_bp.route("/receipts", methods=["POST"])
@require_permission("cash_receipts", "create")
def create_receipt():
    data = request.get_json()
    required = ("source_type", "concept", "amount")
    for field in required:
        if not data.get(field):
            return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": f"{field} es requerido"}), 400
    try:
        receipt = cash.create_cash_receipt(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            source_type=data["source_type"],
            concept=data["concept"],
            amount=data["amount"],
            payment_method=data.get("payment_method", "cash"),
            source_id=data.get("source_id"),
            source_name=data.get("source_name"),
            reference=data.get("reference"),
            notes=data.get("notes"),
        )
        return jsonify(success=True, data=receipt), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "RECEIPT_ERROR", "message": str(e)}), 400


@cash_bp.route("/receipts", methods=["GET"])
@require_permission("cash_receipts", "read")
def list_receipts():
    data = cash.get_cash_receipts(
        g.tenant_id,
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(success=True, data=data)


@cash_bp.route("/receipts/<receipt_id>/void", methods=["POST"])
@require_permission("cash_receipts", "void")
def void_receipt(receipt_id):
    try:
        receipt = cash.void_cash_receipt(g.tenant_id, receipt_id, str(g.current_user.id))
        return jsonify(success=True, data=receipt)
    except ValueError as e:
        return jsonify(success=False, error={"code": "VOID_ERROR", "message": str(e)}), 409


# ── Cash Disbursements ───────────────────────────────────────────


@cash_bp.route("/disbursements", methods=["POST"])
@require_permission("cash_disbursements", "create")
def create_disbursement():
    data = request.get_json()
    required = ("destination_type", "concept", "amount")
    for field in required:
        if not data.get(field):
            return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": f"{field} es requerido"}), 400
    try:
        disb = cash.create_cash_disbursement(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            destination_type=data["destination_type"],
            concept=data["concept"],
            amount=data["amount"],
            payment_method=data.get("payment_method", "cash"),
            puc_code=data.get("puc_code"),
            destination_id=data.get("destination_id"),
            destination_name=data.get("destination_name"),
            reference=data.get("reference"),
            notes=data.get("notes"),
        )
        return jsonify(success=True, data=disb), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "DISBURSEMENT_ERROR", "message": str(e)}), 400


@cash_bp.route("/disbursements", methods=["GET"])
@require_permission("cash_disbursements", "read")
def list_disbursements():
    data = cash.get_cash_disbursements(
        g.tenant_id,
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(success=True, data=data)


@cash_bp.route("/disbursements/<disb_id>/void", methods=["POST"])
@require_permission("cash_disbursements", "void")
def void_disbursement(disb_id):
    try:
        disb = cash.void_cash_disbursement(g.tenant_id, disb_id, str(g.current_user.id))
        return jsonify(success=True, data=disb)
    except ValueError as e:
        return jsonify(success=False, error={"code": "VOID_ERROR", "message": str(e)}), 409


# ── Cash Transfers ───────────────────────────────────────────────


@cash_bp.route("/transfers", methods=["POST"])
@require_permission("cash_transfers", "create")
def create_transfer():
    data = request.get_json()
    required = ("from_account_puc", "to_account_puc", "amount")
    for field in required:
        if not data.get(field):
            return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": f"{field} es requerido"}), 400
    try:
        transfer = cash.create_cash_transfer(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            from_account_puc=data["from_account_puc"],
            to_account_puc=data["to_account_puc"],
            amount=data["amount"],
            reference=data.get("reference"),
            notes=data.get("notes"),
        )
        return jsonify(success=True, data=transfer), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "TRANSFER_ERROR", "message": str(e)}), 400


@cash_bp.route("/transfers", methods=["GET"])
@require_permission("cash_transfers", "read")
def list_transfers():
    data = cash.get_cash_transfers(g.tenant_id)
    return jsonify(success=True, data=data)
