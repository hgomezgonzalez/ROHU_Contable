"""Frontend routes — Serves HTML templates for the SPA-like app."""

from flask import Blueprint, redirect, render_template

frontend_bp = Blueprint("frontend", __name__, url_prefix="/app")


@frontend_bp.route("/")
def index():
    return redirect("/app/dashboard")


@frontend_bp.route("/login")
def login():
    return render_template("auth/login.html")


@frontend_bp.route("/logout")
def logout():
    return """
    <script>
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user');
      localStorage.removeItem('tenant');
      window.location.href = '/app/login';
    </script>
    """


@frontend_bp.route("/dashboard")
def dashboard():
    return render_template("reports/dashboard.html")


@frontend_bp.route("/pos")
def pos():
    return render_template("pos/pos.html")


@frontend_bp.route("/inventory")
def inventory():
    return render_template("inventory/list.html")


@frontend_bp.route("/purchases")
def purchases():
    return render_template("purchases/list.html")


@frontend_bp.route("/reports")
def reports():
    return render_template("reports/reports.html")


@frontend_bp.route("/reports/analytics")
def reports_analytics():
    return render_template("reports/analytics.html")


@frontend_bp.route("/reports/dian")
def reports_dian():
    return render_template("reports/dian.html")


@frontend_bp.route("/reports/financial")
def reports_financial():
    return render_template("reports/financial.html")


@frontend_bp.route("/accounting")
def accounting():
    return render_template("reports/accounting.html")


@frontend_bp.route("/invoicing")
def invoicing():
    return render_template("invoicing/list.html")


@frontend_bp.route("/suppliers")
def suppliers():
    return render_template("purchases/suppliers.html")


@frontend_bp.route("/cash")
def cash():
    return render_template("cash/list.html")


@frontend_bp.route("/customers")
def customers():
    return render_template("customers/list.html")


@frontend_bp.route("/customers/campaigns")
def campaigns():
    return render_template("customers/campaigns.html")


@frontend_bp.route("/cobro/carta/<customer_id>")
def collection_letter(customer_id):
    """Render formal collection letter for a customer (standalone page for printing)."""
    from app.modules.customers.services import build_collection_letter_data
    from flask import request as req
    token = req.args.get("token", "")
    # Verify JWT from query param (since this is a standalone page)
    try:
        from flask_jwt_extended import decode_token
        import json
        decoded = decode_token(token)
        identity = json.loads(decoded["sub"])
        tenant_id = identity["tenant_id"]
    except Exception:
        return "<h3>Acceso no autorizado. Inicie sesión nuevamente.</h3>", 401
    try:
        letter = build_collection_letter_data(tenant_id, customer_id)
        return render_template("customers/collection_letter.html", letter=letter)
    except ValueError as e:
        return f"<h3>Error: {e}</h3>", 404


@frontend_bp.route("/admin/users")
def admin_users():
    return render_template("admin/users.html")


@frontend_bp.route("/admin/settings")
def admin_settings():
    return render_template("admin/settings.html")
