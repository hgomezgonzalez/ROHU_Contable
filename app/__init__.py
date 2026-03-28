"""ROHU Contable — Flask Application Factory."""

from flask import Flask

from app.extensions import db, migrate, jwt, cors, limiter
from app.config import config_by_name


def create_app(config_name: str = "development") -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app)
    limiter.init_app(app)

    # Register blueprints
    _register_blueprints(app)

    # Initialize audit logging
    with app.app_context():
        from app.core.audit import init_audit_listeners
        init_audit_listeners(app)

    # App version and deploy timestamp
    import os
    APP_VERSION = "1.2.1"
    DEPLOY_TIME = os.getenv("DEPLOY_TIME", None)
    if not DEPLOY_TIME:
        from datetime import datetime, timezone
        DEPLOY_TIME = datetime.now(timezone.utc).isoformat()

    # Register health check
    # Security + cache headers
    @app.after_request
    def add_security_headers(response):
        # Prevent browser from caching HTML pages (always get fresh from server)
        if response.content_type and 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(self), microphone=()'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://wa.me https://api.whatsapp.com; "
            "frame-ancestors 'none'; "
            "worker-src 'self';"
        )
        return response

    @app.route("/health")
    def health():
        return {"status": "ok", "service": "rohu-contable", "version": APP_VERSION, "deployed_at": DEPLOY_TIME}

    @app.route("/health/full")
    def health_full():
        """Full health check — verifies all external services and internal state."""
        import time
        checks = {}

        # 1. Database connectivity
        try:
            start = time.time()
            db.session.execute(db.text("SELECT 1"))
            ms = round((time.time() - start) * 1000)
            checks["database"] = {"status": "ok", "response_ms": ms}
        except Exception as e:
            checks["database"] = {"status": "error", "error": str(e)}

        # 2. Database tables exist
        try:
            from app.modules.auth_rbac.models import Tenant
            count = Tenant.query.count()
            checks["db_schema"] = {"status": "ok", "tenants": count}
        except Exception as e:
            checks["db_schema"] = {"status": "error", "error": str(e)}

        # 3. PUC seed status
        try:
            from app.modules.accounting.models import ChartOfAccount
            puc_count = ChartOfAccount.query.count()
            checks["puc"] = {"status": "ok" if puc_count > 0 else "warning", "accounts": puc_count}
        except Exception as e:
            checks["puc"] = {"status": "error", "error": str(e)}

        # 4. Roles & permissions
        try:
            from app.modules.auth_rbac.models import Role, Permission
            roles = Role.query.filter_by(is_system_role=True).count()
            perms = Permission.query.count()
            checks["rbac"] = {"status": "ok" if roles >= 4 and perms >= 40 else "warning",
                              "roles": roles, "permissions": perms}
        except Exception as e:
            checks["rbac"] = {"status": "error", "error": str(e)}

        # 5. SMTP configuration (per tenant)
        try:
            tenants_with_smtp = db.session.execute(
                db.text("SELECT COUNT(*) FROM tenants WHERE smtp_host IS NOT NULL AND smtp_host != ''")
            ).scalar()
            checks["smtp"] = {"status": "ok" if tenants_with_smtp > 0 else "not_configured",
                              "tenants_with_smtp": tenants_with_smtp}
        except Exception as e:
            checks["smtp"] = {"status": "error", "error": str(e)}

        # 6. Factura Electrónica DIAN (PTA)
        try:
            tenants_pta = db.session.execute(db.text(
                "SELECT name, pta_provider, "
                "CASE WHEN pta_api_key IS NOT NULL AND pta_api_key != '' THEN true ELSE false END as configured "
                "FROM tenants WHERE is_active = true"
            )).fetchall()
            pta_details = []
            for t in tenants_pta:
                pta_details.append({
                    "tenant": t[0],
                    "provider": t[1] or "sin configurar",
                    "api_key_configured": bool(t[2]),
                })
            any_configured = any(d["api_key_configured"] for d in pta_details)
            checks["factura_electronica"] = {
                "status": "ok" if any_configured else "not_configured",
                "provider": pta_details[0]["provider"] if pta_details else "N/A",
                "tenants": pta_details,
                "note": "Conectado a PTA DIAN" if any_configured else "Configure API Key del PTA en Mi Negocio",
            }
        except Exception as e:
            checks["factura_electronica"] = {"status": "error", "error": str(e)}

        # 7. WhatsApp notifications
        try:
            # Check if there are customers with phone numbers for WhatsApp
            customers_with_phone = db.session.execute(db.text(
                "SELECT COUNT(*) FROM customers WHERE phone IS NOT NULL AND phone != ''"
            )).scalar()
            # Test generate a wa.me link
            test_link = "https://wa.me/573001234567?text=Test" if customers_with_phone > 0 else None
            checks["whatsapp"] = {
                "status": "ok" if customers_with_phone > 0 else "not_configured",
                "customers_with_phone": customers_with_phone,
                "method": "Links wa.me (gratis, sin API)",
                "note": f"{customers_with_phone} clientes con teléfono para WhatsApp" if customers_with_phone > 0 else "Registre clientes con número de celular",
            }
        except Exception as e:
            checks["whatsapp"] = {"status": "error", "error": str(e)}

        # 8. Tesseract OCR
        try:
            import subprocess
            result = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=5)
            version = result.stdout.split('\n')[0] if result.returncode == 0 else "not found"
            checks["ocr_tesseract"] = {"status": "ok" if result.returncode == 0 else "unavailable",
                                        "version": version}
        except Exception:
            checks["ocr_tesseract"] = {"status": "unavailable", "error": "Tesseract not installed"}

        # 7. Disk / static files
        try:
            import os
            sw_exists = os.path.exists(os.path.join(app.static_folder, "sw.js"))
            css_exists = os.path.exists(os.path.join(app.static_folder, "css", "rohu.css"))
            checks["static_files"] = {"status": "ok" if sw_exists and css_exists else "error",
                                       "sw.js": sw_exists, "rohu.css": css_exists}
        except Exception as e:
            checks["static_files"] = {"status": "error", "error": str(e)}

        # 8. PWA / Offline readiness
        try:
            import os
            sw_path = os.path.join(app.static_folder, "sw.js")
            offline_path = os.path.join(app.static_folder, "js", "rohu-offline.js")
            manifest_path = os.path.join(app.static_folder, "manifest.json")
            sw_ok = os.path.exists(sw_path)
            offline_ok = os.path.exists(offline_path)
            manifest_ok = os.path.exists(manifest_path)

            # Check SW has correct cache version
            sw_version = "unknown"
            if sw_ok:
                with open(sw_path, 'r') as f:
                    content = f.read(500)
                    import re
                    m = re.search(r"CACHE_VERSION\s*=\s*['\"](\d+)['\"]", content)
                    if m:
                        sw_version = f"v{m.group(1)}"

            checks["pwa_offline"] = {
                "status": "ok" if all([sw_ok, offline_ok, manifest_ok]) else "error",
                "service_worker": sw_ok,
                "offline_module": offline_ok,
                "manifest": manifest_ok,
                "cache_version": sw_version,
                "features": "Ventas offline con cola de sincronización, cache de productos, auto-sync al reconectar",
            }
        except Exception as e:
            checks["pwa_offline"] = {"status": "error", "error": str(e)}

        # Overall status
        has_errors = any(c.get("status") == "error" for c in checks.values())
        overall = "error" if has_errors else "ok"

        return {"status": overall, "service": "rohu-contable", "version": APP_VERSION,
                "deployed_at": DEPLOY_TIME, "checks": checks}

    # Serve SW from root scope (required for PWA)
    @app.route("/sw.js")
    def service_worker():
        from flask import send_from_directory
        return send_from_directory(
            app.static_folder, "sw.js",
            mimetype="application/javascript",
            max_age=0,
        )

    return app


def _register_blueprints(app: Flask) -> None:
    """Register all module blueprints."""
    from app.modules.auth_rbac.blueprint import auth_bp
    from app.modules.inventory.blueprint import inventory_bp
    from app.modules.pos.blueprint import pos_bp
    from app.modules.accounting.blueprint import accounting_bp
    from app.modules.purchases.blueprint import purchases_bp
    from app.modules.reports.blueprint import reports_bp
    from app.modules.invoicing.blueprint import invoicing_bp
    from app.modules.customers.blueprint import customers_bp
    from app.modules.cash.blueprint import cash_bp
    from app.frontend import frontend_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(accounting_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(invoicing_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(cash_bp)
    app.register_blueprint(frontend_bp)

    # Root redirect
    @app.route("/")
    def root():
        from flask import redirect
        return redirect("/app/login")
