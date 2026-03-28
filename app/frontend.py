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


@frontend_bp.route("/admin/users")
def admin_users():
    return render_template("admin/users.html")


@frontend_bp.route("/admin/settings")
def admin_settings():
    return render_template("admin/settings.html")
