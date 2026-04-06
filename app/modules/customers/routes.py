"""Customer routes — REST API endpoints."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.customers import services as cust
from app.modules.customers.blueprint import customers_bp


@customers_bp.route("", methods=["GET"])
@require_permission("customers", "read")
def list_customers():
    search = request.args.get("q")
    data = cust.get_customers(g.tenant_id, search=search)
    return jsonify(success=True, data=data)


@customers_bp.route("", methods=["POST"])
@require_permission("customers", "create")
def create_customer():
    data = request.get_json()
    if not data.get("name"):
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "name es requerido"}), 400

    customer = cust.create_customer(
        tenant_id=g.tenant_id,
        created_by=str(g.current_user.id),
        name=data["name"],
        tax_id=data.get("tax_id"),
        tax_id_type=data.get("tax_id_type", "CC"),
        contact_name=data.get("contact_name"),
        phone=data.get("phone"),
        email=data.get("email"),
        address=data.get("address"),
        city=data.get("city"),
        credit_limit=data.get("credit_limit", 0),
        credit_days=data.get("credit_days", 0),
        notes=data.get("notes"),
    )
    return jsonify(success=True, data=customer), 201


@customers_bp.route("/<customer_id>", methods=["GET"])
@require_permission("customers", "read")
def get_customer(customer_id):
    try:
        customer = cust.get_customer(g.tenant_id, customer_id)
        return jsonify(success=True, data=customer)
    except ValueError as e:
        return jsonify(success=False, error={"code": "NOT_FOUND", "message": str(e)}), 404


@customers_bp.route("/<customer_id>", methods=["PATCH"])
@require_permission("customers", "update")
def update_customer(customer_id):
    data = request.get_json()
    try:
        customer = cust.update_customer(g.tenant_id, customer_id, **data)
        return jsonify(success=True, data=customer)
    except ValueError as e:
        return jsonify(success=False, error={"code": "UPDATE_ERROR", "message": str(e)}), 400


# ── Customer Payments (Abonos) ───────────────────────────────────


@customers_bp.route("/<customer_id>/payments", methods=["POST"])
@require_permission("customer_payments", "create")
def create_payment(customer_id):
    data = request.get_json()
    if not data.get("amount"):
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "amount es requerido"}), 400
    try:
        payment = cust.create_customer_payment(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            customer_id=customer_id,
            amount=data["amount"],
            payment_method=data.get("payment_method", "cash"),
            sale_id=data.get("sale_id"),
            reference=data.get("reference"),
            notes=data.get("notes"),
        )
        return jsonify(success=True, data=payment), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "PAYMENT_ERROR", "message": str(e)}), 400


@customers_bp.route("/<customer_id>/payments", methods=["GET"])
@require_permission("customer_payments", "read")
def list_payments(customer_id):
    payments = cust.get_customer_payments(g.tenant_id, customer_id)
    return jsonify(success=True, data=payments)


@customers_bp.route("/<customer_id>/statement", methods=["GET"])
@require_permission("customers", "read")
def customer_statement(customer_id):
    try:
        statement = cust.get_customer_statement(g.tenant_id, customer_id)
        return jsonify(success=True, data=statement)
    except ValueError as e:
        return jsonify(success=False, error={"code": "NOT_FOUND", "message": str(e)}), 404


@customers_bp.route("/<customer_id>/write-off", methods=["POST"])
@require_permission("customers", "delete")
def write_off(customer_id):
    data = request.get_json() or {}
    try:
        result = cust.write_off_customer(
            g.tenant_id,
            customer_id,
            str(g.current_user.id),
            sale_id=data.get("sale_id"),
        )
        return jsonify(success=True, data=result)
    except ValueError as e:
        return jsonify(success=False, error={"code": "WRITE_OFF_ERROR", "message": str(e)}), 400


# ── Sales Debit Notes ────────────────────────────────────────────


@customers_bp.route("/<customer_id>/debit-notes", methods=["POST"])
@require_permission("customers", "update")
def create_debit_note(customer_id):
    data = request.get_json()
    if not data.get("reason") or not data.get("amount"):
        return (
            jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "reason y amount son requeridos"}),
            400,
        )
    try:
        dn = cust.create_sales_debit_note(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            customer_id=customer_id,
            reason=data["reason"],
            amount=data["amount"],
            tax_amount=data.get("tax_amount", 0),
            sale_id=data.get("sale_id"),
        )
        return jsonify(success=True, data=dn), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "DN_ERROR", "message": str(e)}), 400


@customers_bp.route("/<customer_id>/debit-notes", methods=["GET"])
@require_permission("customers", "read")
def list_debit_notes(customer_id):
    notes = cust.get_sales_debit_notes(g.tenant_id, customer_id=customer_id)
    return jsonify(success=True, data=notes)


# ── Collection Campaigns ─────────────────────────────────────────


@customers_bp.route("/campaigns/preview", methods=["POST"])
@require_permission("customers", "read")
def preview_campaign():
    """Preview which customers would be included in a campaign without creating it."""
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app.modules.pos.models import Sale
    from app.modules.pos.services import mark_overdue_sales

    data = request.get_json() or {}
    min_days = data.get("min_days_overdue", 1)
    min_amount = data.get("min_amount_due", 0)

    mark_overdue_sales(g.tenant_id)

    now = datetime.now(timezone.utc)
    sales = Sale.query.filter(
        Sale.tenant_id == g.tenant_id,
        Sale.sale_type == "credit",
        Sale.status == "completed",
        Sale.payment_status.in_(["pending", "partial", "overdue"]),
        Sale.amount_due > min_amount,
    ).all()

    customers = {}
    for sale in sales:
        days = (now - (sale.due_date or sale.sale_date)).days
        if days < min_days or not sale.customer_id:
            continue
        cid = str(sale.customer_id)
        if cid not in customers:
            customers[cid] = {"name": sale.customer_name, "total_due": 0, "max_days": 0, "invoices": 0}
        customers[cid]["total_due"] += float(sale.amount_due)
        customers[cid]["max_days"] = max(customers[cid]["max_days"], days)
        customers[cid]["invoices"] += 1

    result = sorted(customers.values(), key=lambda x: x["total_due"], reverse=True)
    return jsonify(
        success=True, data=result, total_customers=len(result), total_amount=sum(c["total_due"] for c in result)
    )


@customers_bp.route("/campaigns", methods=["POST"])
@require_permission("customers", "create")
def create_campaign():
    data = request.get_json()
    if not data.get("name"):
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "name es requerido"}), 400
    try:
        campaign = cust.create_collection_campaign(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            name=data["name"],
            target_type=data.get("target_type", "all_overdue"),
            min_days_overdue=data.get("min_days_overdue", 1),
            min_amount_due=data.get("min_amount_due", 0),
            message_template=data.get("message_template"),
        )
        return jsonify(success=True, data=campaign), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "CAMPAIGN_ERROR", "message": str(e)}), 400


@customers_bp.route("/campaigns", methods=["GET"])
@require_permission("customers", "read")
def list_campaigns():
    data = cust.get_collection_campaigns(g.tenant_id)
    return jsonify(success=True, data=data)


@customers_bp.route("/campaigns/<campaign_id>", methods=["GET"])
@require_permission("customers", "read")
def get_campaign(campaign_id):
    try:
        data = cust.get_collection_campaign(g.tenant_id, campaign_id)
        return jsonify(success=True, data=data)
    except ValueError as e:
        return jsonify(success=False, error={"code": "NOT_FOUND", "message": str(e)}), 404


@customers_bp.route("/campaigns/<campaign_id>/items/<item_id>", methods=["PATCH"])
@require_permission("customers", "update")
def update_campaign_item(campaign_id, item_id):
    data = request.get_json()
    try:
        item = cust.update_campaign_item(g.tenant_id, campaign_id, item_id, **data)
        return jsonify(success=True, data=item)
    except ValueError as e:
        return jsonify(success=False, error={"code": "UPDATE_ERROR", "message": str(e)}), 400


@customers_bp.route("/campaigns/<campaign_id>/execute", methods=["POST"])
@require_permission("customers", "create")
def execute_campaign(campaign_id):
    try:
        data = cust.execute_campaign(g.tenant_id, campaign_id)
        return jsonify(success=True, data=data)
    except ValueError as e:
        return jsonify(success=False, error={"code": "EXECUTE_ERROR", "message": str(e)}), 409


@customers_bp.route("/campaigns/<campaign_id>/send-notifications", methods=["POST"])
@require_permission("customers", "create")
def send_campaign_notifications(campaign_id):
    """Send email notifications to all customers in a campaign."""
    from app.core.email_service import send_campaign_emails
    from app.modules.auth_rbac.models import Tenant

    tenant = Tenant.query.get(g.tenant_id)
    if not tenant or not tenant.smtp_host:
        return (
            jsonify(
                success=False,
                error={
                    "code": "SMTP_NOT_CONFIGURED",
                    "message": "Configure el servidor SMTP en Mi Negocio > Notificaciones para enviar emails.",
                },
            ),
            400,
        )

    campaign_data = cust.get_collection_campaign(g.tenant_id, campaign_id)

    smtp_config = {
        "host": tenant.smtp_host,
        "port": tenant.smtp_port or 587,
        "user": tenant.smtp_user,
        "password": tenant.smtp_password,
        "from_email": tenant.smtp_from_email or tenant.smtp_user,
        "business_name": tenant.name,
    }

    items_for_email = [
        {
            "customer_email": i.get("customer_email"),
            "rendered_message": i.get("rendered_message"),
            "customer_name": i.get("customer_name"),
        }
        for i in campaign_data.get("items", [])
    ]

    result = send_campaign_emails(smtp_config, items_for_email)

    # Update contacted items
    if result["sent"] > 0:
        for i, item_data in enumerate(campaign_data.get("items", [])):
            if item_data.get("customer_email") and i < len(result.get("results", [])):
                r = result["results"][i] if i < len(result["results"]) else None
                if r and r.get("success"):
                    try:
                        cust.update_campaign_item(
                            g.tenant_id,
                            campaign_id,
                            item_data["id"],
                            contact_status="contacted",
                            contact_method="email",
                        )
                    except Exception:
                        pass

    return jsonify(success=True, data=result)


@customers_bp.route("/campaigns/<campaign_id>/cancel", methods=["POST"])
@require_permission("customers", "create")
def cancel_campaign(campaign_id):
    try:
        data = cust.cancel_campaign(g.tenant_id, campaign_id)
        return jsonify(success=True, data=data)
    except ValueError as e:
        return jsonify(success=False, error={"code": "CANCEL_ERROR", "message": str(e)}), 409


@customers_bp.route("/campaigns/<campaign_id>/complete", methods=["POST"])
@require_permission("customers", "create")
def complete_campaign(campaign_id):
    try:
        data = cust.complete_campaign(g.tenant_id, campaign_id)
        return jsonify(success=True, data=data)
    except ValueError as e:
        return jsonify(success=False, error={"code": "COMPLETE_ERROR", "message": str(e)}), 409


# ── Aging Report ─────────────────────────────────────────────────


@customers_bp.route("/aging", methods=["GET"])
@require_permission("reports", "read")
def aging_report():
    data = cust.get_aging_report(g.tenant_id)
    return jsonify(success=True, data=data)
