"""Electronic invoicing routes."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.invoicing import services as inv
from app.modules.invoicing.blueprint import invoicing_bp


@invoicing_bp.route("/generate/<sale_id>", methods=["POST"])
@require_permission("sales", "create")
def generate(sale_id):
    data = request.get_json() or {}
    try:
        invoice = inv.generate_invoice(
            tenant_id=g.tenant_id,
            sale_id=sale_id,
            created_by=str(g.current_user.id),
            customer_name=data.get("customer_name"),
            customer_tax_id=data.get("customer_tax_id"),
            customer_email=data.get("customer_email"),
        )
        return jsonify(success=True, data=invoice), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "INVOICE_ERROR", "message": str(e)}), 400


@invoicing_bp.route("/credit-note/<credit_note_id>", methods=["POST"])
@require_permission("sales", "void")
def generate_credit_note(credit_note_id):
    try:
        invoice = inv.generate_credit_note_invoice(
            tenant_id=g.tenant_id,
            credit_note_id=credit_note_id,
            created_by=str(g.current_user.id),
        )
        return jsonify(success=True, data=invoice), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "CN_INVOICE_ERROR", "message": str(e)}), 400


@invoicing_bp.route("/", methods=["GET"])
@require_permission("sales", "read")
def list_all():
    result = inv.list_invoices(
        tenant_id=g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
    )
    return jsonify(success=True, **result)
