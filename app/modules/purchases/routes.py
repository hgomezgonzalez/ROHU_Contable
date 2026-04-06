"""Purchases routes — REST API endpoints."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.purchases import services as pur
from app.modules.purchases.blueprint import purchases_bp

# ── Suppliers ─────────────────────────────────────────────────────


@purchases_bp.route("/suppliers", methods=["GET"])
@require_permission("purchases", "read")
def list_suppliers():
    suppliers = pur.get_suppliers(g.tenant_id)
    return jsonify(success=True, data=suppliers)


@purchases_bp.route("/suppliers", methods=["POST"])
@require_permission("purchases", "create")
def create_supplier():
    data = request.get_json()
    if not data.get("name"):
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "name es requerido"}), 400

    supplier = pur.create_supplier(
        tenant_id=g.tenant_id,
        created_by=str(g.current_user.id),
        name=data["name"],
        tax_id=data.get("tax_id"),
        contact_name=data.get("contact_name"),
        phone=data.get("phone"),
        email=data.get("email"),
        address=data.get("address"),
        city=data.get("city"),
        payment_terms_days=data.get("payment_terms_days", 0),
    )
    return jsonify(success=True, data=supplier), 201


@purchases_bp.route("/suppliers/<supplier_id>", methods=["PATCH"])
@require_permission("purchases", "create")
def edit_supplier(supplier_id):
    data = request.get_json()
    try:
        supplier = pur.update_supplier(g.tenant_id, supplier_id, **data)
        return jsonify(success=True, data=supplier)
    except ValueError as e:
        return jsonify(success=False, error={"code": "SUPPLIER_ERROR", "message": str(e)}), 400


# ── Purchase Orders ───────────────────────────────────────────────


@purchases_bp.route("/orders", methods=["GET"])
@require_permission("purchases", "read")
def list_orders():
    result = pur.list_purchase_orders(
        tenant_id=g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
        status=request.args.get("status"),
        supplier_id=request.args.get("supplier_id"),
    )
    return jsonify(success=True, **result)


@purchases_bp.route("/orders", methods=["POST"])
@require_permission("purchases", "create")
def create_order():
    data = request.get_json()
    if not data.get("supplier_id") or not data.get("items"):
        return (
            jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "supplier_id e items son requeridos"}),
            400,
        )

    try:
        po = pur.create_purchase_order(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            supplier_id=data["supplier_id"],
            items=data["items"],
            payment_type=data.get("payment_type", "cash"),
            supplier_invoice=data.get("supplier_invoice"),
            notes=data.get("notes"),
        )
        return jsonify(success=True, data=po), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "PO_CREATE_ERROR", "message": str(e)}), 400


@purchases_bp.route("/orders/<po_id>", methods=["GET"])
@require_permission("purchases", "read")
def get_order(po_id):
    try:
        po = pur.get_purchase_order(g.tenant_id, po_id)
        return jsonify(success=True, data=po)
    except ValueError as e:
        return jsonify(success=False, error={"code": "PO_NOT_FOUND", "message": str(e)}), 404


@purchases_bp.route("/orders/<po_id>", methods=["PATCH"])
@require_permission("purchases", "create")
def edit_order(po_id):
    data = request.get_json()
    try:
        po = pur.update_purchase_order(g.tenant_id, po_id, **data)
        return jsonify(success=True, data=po)
    except ValueError as e:
        return jsonify(success=False, error={"code": "PO_EDIT_ERROR", "message": str(e)}), 409


@purchases_bp.route("/orders/<po_id>/send", methods=["POST"])
@require_permission("purchases", "approve")
def send_order(po_id):
    try:
        po = pur.send_purchase_order(g.tenant_id, po_id)
        return jsonify(success=True, data=po)
    except ValueError as e:
        return jsonify(success=False, error={"code": "PO_SEND_ERROR", "message": str(e)}), 409


@purchases_bp.route("/orders/<po_id>/receive", methods=["POST"])
@require_permission("purchases", "approve")
def receive_order(po_id):
    data = request.get_json() or {}
    try:
        po = pur.receive_purchase_order(
            tenant_id=g.tenant_id,
            po_id=po_id,
            user_id=str(g.current_user.id),
            received_items=data.get("received_items"),
        )
        return jsonify(success=True, data=po)
    except ValueError as e:
        return jsonify(success=False, error={"code": "PO_RECEIVE_ERROR", "message": str(e)}), 409


@purchases_bp.route("/orders/<po_id>/cancel", methods=["POST"])
@require_permission("purchases", "approve")
def cancel_order(po_id):
    try:
        po = pur.cancel_purchase_order(g.tenant_id, po_id)
        return jsonify(success=True, data=po)
    except ValueError as e:
        return jsonify(success=False, error={"code": "PO_CANCEL_ERROR", "message": str(e)}), 409


# ── Supplier Payments ────────────────────────────────────────────


@purchases_bp.route("/suppliers/<supplier_id>/payments", methods=["POST"])
@require_permission("supplier_payments", "create")
def create_payment(supplier_id):
    data = request.get_json()
    if not data.get("amount"):
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "amount es requerido"}), 400
    try:
        payment = pur.create_supplier_payment(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            supplier_id=supplier_id,
            amount=data["amount"],
            payment_method=data.get("payment_method", "cash"),
            purchase_order_id=data.get("purchase_order_id"),
            reference=data.get("reference"),
            bank_account=data.get("bank_account"),
            notes=data.get("notes"),
        )
        return jsonify(success=True, data=payment), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "PAYMENT_ERROR", "message": str(e)}), 400


@purchases_bp.route("/suppliers/<supplier_id>/payments", methods=["GET"])
@require_permission("supplier_payments", "read")
def list_payments(supplier_id):
    payments = pur.get_supplier_payments(g.tenant_id, supplier_id)
    return jsonify(success=True, data=payments)


@purchases_bp.route("/suppliers/<supplier_id>/balance", methods=["GET"])
@require_permission("supplier_payments", "read")
def supplier_balance(supplier_id):
    balance = pur.get_supplier_balance(g.tenant_id, supplier_id)
    return jsonify(success=True, data=balance)


@purchases_bp.route("/payments/<payment_id>/void", methods=["POST"])
@require_permission("supplier_payments", "void")
def void_payment(payment_id):
    try:
        payment = pur.void_supplier_payment(g.tenant_id, payment_id, str(g.current_user.id))
        return jsonify(success=True, data=payment)
    except ValueError as e:
        return jsonify(success=False, error={"code": "VOID_ERROR", "message": str(e)}), 409


# ── Purchase Credit Notes ────────────────────────────────────────


@purchases_bp.route("/credit-notes", methods=["GET"])
@require_permission("purchase_credit_notes", "read")
def list_credit_notes():
    supplier_id = request.args.get("supplier_id")
    notes = pur.get_purchase_credit_notes(g.tenant_id, supplier_id=supplier_id)
    return jsonify(success=True, data=notes)


@purchases_bp.route("/orders/<po_id>/credit-note", methods=["POST"])
@require_permission("purchase_credit_notes", "create")
def create_credit_note(po_id):
    data = request.get_json()
    if not data.get("reason") or not data.get("items"):
        return (
            jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "reason e items son requeridos"}),
            400,
        )

    try:
        po_obj = pur._get_po(g.tenant_id, po_id)
        cn = pur.create_purchase_credit_note(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            supplier_id=str(po_obj.supplier_id),
            reason=data["reason"],
            items=data["items"],
            purchase_order_id=po_id,
        )
        return jsonify(success=True, data=cn), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "CN_ERROR", "message": str(e)}), 400


# ── Purchase Debit Notes ─────────────────────────────────────────


@purchases_bp.route("/debit-notes", methods=["GET"])
@require_permission("purchases", "read")
def list_debit_notes_all():
    supplier_id = request.args.get("supplier_id")
    notes = pur.get_purchase_debit_notes(g.tenant_id, supplier_id=supplier_id)
    return jsonify(success=True, data=notes)


@purchases_bp.route("/suppliers/<supplier_id>/debit-notes", methods=["POST"])
@require_permission("purchase_credit_notes", "create")
def create_debit_note(supplier_id):
    data = request.get_json()
    if not data.get("reason") or not data.get("amount"):
        return (
            jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "reason y amount son requeridos"}),
            400,
        )

    try:
        dn = pur.create_purchase_debit_note(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            supplier_id=supplier_id,
            reason=data["reason"],
            amount=data["amount"],
            tax_amount=data.get("tax_amount", 0),
            purchase_order_id=data.get("purchase_order_id"),
        )
        return jsonify(success=True, data=dn), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "DN_ERROR", "message": str(e)}), 400
