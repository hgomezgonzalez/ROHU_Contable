"""Accounting routes — REST API endpoints."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.accounting.blueprint import accounting_bp
from app.modules.accounting import services as acc


@accounting_bp.route("/accounts", methods=["GET"])
@require_permission("chart_of_accounts", "manage")
def list_accounts():
    accounts = acc.get_chart_of_accounts(g.tenant_id)
    return jsonify(success=True, data=accounts)


@accounting_bp.route("/accounts", methods=["POST"])
@require_permission("chart_of_accounts", "manage")
def create_account():
    data = request.get_json()
    required = ("puc_code", "name", "account_type", "normal_balance")
    for f in required:
        if not data.get(f):
            return jsonify(success=False, error={
                "code": "VALIDATION_ERROR", "message": f"{f} es requerido"
            }), 400
    try:
        account = acc.create_account(
            tenant_id=g.tenant_id,
            puc_code=data["puc_code"], name=data["name"],
            account_type=data["account_type"],
            normal_balance=data["normal_balance"],
            parent_code=data.get("parent_code"),
        )
        return jsonify(success=True, data=account), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "ACCOUNT_ERROR", "message": str(e)}), 400


@accounting_bp.route("/accounts/<account_id>", methods=["PATCH"])
@require_permission("chart_of_accounts", "manage")
def update_account(account_id):
    data = request.get_json()
    try:
        account = acc.update_account(g.tenant_id, account_id, **data)
        return jsonify(success=True, data=account)
    except ValueError as e:
        return jsonify(success=False, error={"code": "UPDATE_ERROR", "message": str(e)}), 400


@accounting_bp.route("/accounts/<account_id>", methods=["DELETE"])
@require_permission("chart_of_accounts", "manage")
def delete_account(account_id):
    try:
        result = acc.delete_account(g.tenant_id, account_id)
        return jsonify(success=True, data=result)
    except ValueError as e:
        code = "SYSTEM_ACCOUNT" if "sistema" in str(e) else "HAS_MOVEMENTS" if "movimientos" in str(e) else "DELETE_ERROR"
        status = 403 if "sistema" in str(e) else 409 if "movimientos" in str(e) else 400
        return jsonify(success=False, error={"code": code, "message": str(e)}), status


@accounting_bp.route("/accounts/seed", methods=["POST"])
@require_permission("chart_of_accounts", "manage")
def seed_accounts():
    count = acc.seed_chart_of_accounts(g.tenant_id)
    return jsonify(success=True, data={"accounts_seeded": count})


@accounting_bp.route("/journal", methods=["GET"])
@require_permission("journal_entries", "read")
def list_entries():
    result = acc.get_journal_entries(
        tenant_id=g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
        entry_type=request.args.get("type"),
    )
    return jsonify(success=True, **result)


@accounting_bp.route("/journal", methods=["POST"])
@require_permission("journal_entries", "create")
def create_entry():
    data = request.get_json()
    if not data.get("description") or not data.get("lines"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR",
            "message": "description y lines son requeridos"
        }), 400

    try:
        from app.extensions import db
        entry = acc.create_journal_entry(
            tenant_id=g.tenant_id,
            created_by=str(g.current_user.id),
            entry_type=data.get("entry_type", "MANUAL"),
            description=data["description"],
            lines=data["lines"],
        )
        db.session.commit()  # Explicit commit for direct HTTP calls
        return jsonify(success=True, data=entry), 201
    except ValueError as e:
        code = "ACCOUNTING_IMBALANCE" if "desbalanceado" in str(e) else "JOURNAL_ERROR"
        return jsonify(success=False, error={"code": code, "message": str(e)}), 400


@accounting_bp.route("/trial-balance", methods=["GET"])
@require_permission("journal_entries", "read")
def trial_balance():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    balance = acc.get_trial_balance(g.tenant_id, year, month)
    return jsonify(success=True, data=balance)


@accounting_bp.route("/periods/<int:year>/<int:month>/close", methods=["POST"])
@require_permission("journal_entries", "close")
def close_period(year, month):
    try:
        result = acc.monthly_close(
            tenant_id=g.tenant_id, year=year, month=month,
            user_id=str(g.current_user.id),
        )
        return jsonify(success=True, data=result)
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "PERIOD_CLOSE_ERROR", "message": str(e)
        }), 409


@accounting_bp.route("/periods/<int:year>/<int:month>/reopen", methods=["POST"])
@require_permission("journal_entries", "close")
def reopen_period_route(year, month):
    try:
        period = acc.reopen_period(
            tenant_id=g.tenant_id, year=year, month=month,
            user_id=str(g.current_user.id),
        )
        return jsonify(success=True, data=period)
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "PERIOD_REOPEN_ERROR", "message": str(e)
        }), 409


# ── Expenses ─────────────────────────────────────────────────────

@accounting_bp.route("/expenses", methods=["POST"])
@require_permission("journal_entries", "create")
def create_expense():
    data = request.get_json()
    if not data.get("puc_code") or not data.get("concept") or not data.get("amount"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR",
            "message": "puc_code, concept y amount son requeridos"
        }), 400
    try:
        expense = acc.create_expense(
            tenant_id=g.tenant_id, created_by=str(g.current_user.id),
            puc_code=data["puc_code"], concept=data["concept"],
            amount=data["amount"], tax_amount=data.get("tax_amount", 0),
            payment_status=data.get("payment_status", "paid"),
            payment_method=data.get("payment_method", "cash"),
            supplier_id=data.get("supplier_id"),
            receipt_reference=data.get("receipt_reference"),
            notes=data.get("notes"),
        )
        return jsonify(success=True, data=expense), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "EXPENSE_ERROR", "message": str(e)}), 400


@accounting_bp.route("/expenses", methods=["GET"])
@require_permission("journal_entries", "read")
def list_expenses():
    result = acc.get_expenses(
        g.tenant_id,
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
    )
    return jsonify(success=True, **result)


@accounting_bp.route("/expenses/<expense_id>/pay", methods=["POST"])
@require_permission("journal_entries", "create")
def pay_expense(expense_id):
    data = request.get_json() or {}
    try:
        expense = acc.pay_expense(
            g.tenant_id, expense_id, str(g.current_user.id),
            payment_method=data.get("payment_method", "cash"),
        )
        return jsonify(success=True, data=expense)
    except ValueError as e:
        return jsonify(success=False, error={"code": "PAY_ERROR", "message": str(e)}), 409


# ── Withholdings ─────────────────────────────────────────────────

@accounting_bp.route("/withholdings", methods=["GET"])
@require_permission("chart_of_accounts", "manage")
def list_withholdings():
    data = acc.get_withholdings(g.tenant_id)
    return jsonify(success=True, data=data)


@accounting_bp.route("/withholdings/seed", methods=["POST"])
@require_permission("chart_of_accounts", "manage")
def seed_withholdings():
    count = acc.seed_withholdings(g.tenant_id)
    return jsonify(success=True, data={"withholdings_seeded": count})
