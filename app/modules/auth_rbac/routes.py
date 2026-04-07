"""Auth RBAC routes — REST API endpoints."""

import json

from flask import jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
)
from flask_jwt_extended import get_jwt_identity as _get_jwt_identity
from flask_jwt_extended import (
    jwt_required,
)


def _make_identity(user_id: str, tenant_id: str) -> str:
    """Serialize identity as JSON string (Flask-JWT-Extended requires string subject)."""
    return json.dumps({"user_id": user_id, "tenant_id": tenant_id})


def get_jwt_identity() -> dict:
    """Deserialize JWT identity from JSON string back to dict."""
    raw = _get_jwt_identity()
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


from app.extensions import limiter
from app.modules.auth_rbac.blueprint import auth_bp
from app.modules.auth_rbac.services import (
    authenticate,
    create_custom_role,
    create_refresh_token_record,
    create_tenant,
    create_user,
    deactivate_user,
    get_tenant,
    get_tenant_roles,
    get_users_by_tenant,
    list_permissions_grouped,
    require_permission,
    reset_tenant_data,
    reset_user_password,
    revoke_all_user_tokens,
    update_role_permissions,
    update_tenant,
    update_user,
)


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("3 per minute; 10 per hour")
def register():
    """Register a new tenant with its owner user."""
    data = request.get_json()
    required = ["name", "tax_id", "email", "owner_first_name", "owner_last_name", "owner_email", "owner_password"]

    missing = [f for f in required if not data.get(f)]
    if missing:
        return (
            jsonify(
                success=False,
                error={
                    "code": "VALIDATION_ERROR",
                    "message": f"Campos requeridos: {', '.join(missing)}",
                },
            ),
            400,
        )

    if len(data["owner_password"]) < 8:
        return (
            jsonify(
                success=False,
                error={
                    "code": "VALIDATION_ERROR",
                    "message": "La contraseña debe tener al menos 8 caracteres",
                },
            ),
            400,
        )

    try:
        result = create_tenant(**{k: data[k] for k in required})
        # Seed PUC (chart of accounts) for the new tenant
        from app.modules.accounting.services import seed_chart_of_accounts

        seed_chart_of_accounts(result["tenant"]["id"])
        # Generate tokens for immediate login
        identity = _make_identity(result["user"]["id"], result["tenant"]["id"])
        access_token = create_access_token(identity=identity)
        refresh_token = create_refresh_token(identity=identity)
        create_refresh_token_record(
            result["user"]["id"], result["tenant"]["id"], refresh_token, request.remote_addr or ""
        )

        return (
            jsonify(
                success=True,
                data={**result, "access_token": access_token, "refresh_token": refresh_token},
            ),
            201,
        )
    except ValueError as e:
        return jsonify(success=False, error={"code": "REGISTRATION_ERROR", "message": str(e)}), 409


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def login():
    """Authenticate a user and return JWT tokens."""
    data = request.get_json()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return (
            jsonify(
                success=False,
                error={
                    "code": "VALIDATION_ERROR",
                    "message": "Email y contraseña son requeridos",
                },
            ),
            400,
        )

    try:
        user_data = authenticate(email, password)
        identity = _make_identity(user_data["id"], user_data["tenant_id"])
        access_token = create_access_token(identity=identity)
        refresh_token = create_refresh_token(identity=identity)
        create_refresh_token_record(user_data["id"], user_data["tenant_id"], refresh_token, request.remote_addr or "")

        return jsonify(
            success=True,
            data={
                "user": user_data,
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
        )
    except ValueError as e:
        return (
            jsonify(
                success=False,
                error={
                    "code": "AUTH_INVALID_CREDENTIALS",
                    "message": str(e),
                },
            ),
            401,
        )


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """Refresh an access token using a valid refresh token."""
    raw = _get_jwt_identity()
    access_token = create_access_token(identity=raw)
    return jsonify(success=True, data={"access_token": access_token})


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """Revoke all refresh tokens for the current user."""
    identity = get_jwt_identity()
    count = revoke_all_user_tokens(identity["user_id"])
    return jsonify(success=True, data={"revoked_tokens": count})


@auth_bp.route("/tenant", methods=["GET"])
@require_permission("tenants", "manage")
def get_tenant_info():
    """Get current tenant details."""
    from flask import g

    tenant = get_tenant(g.tenant_id)
    return jsonify(success=True, data=tenant)


@auth_bp.route("/tenant", methods=["PATCH"])
@require_permission("tenants", "manage")
def update_tenant_info():
    """Update current tenant configuration."""
    from flask import g

    data = request.get_json()
    try:
        tenant = update_tenant(g.tenant_id, **data)
        return jsonify(success=True, data=tenant)
    except ValueError as e:
        return jsonify(success=False, error={"code": "TENANT_UPDATE_ERROR", "message": str(e)}), 400


@auth_bp.route("/tenant/logo", methods=["POST"])
@require_permission("tenants", "manage")
def upload_logo():
    """Upload tenant logo as image file. Stores as base64 data URI in DB."""
    from flask import g

    if "logo" not in request.files:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "Campo 'logo' requerido"}), 400

    file = request.files["logo"]
    if not file.filename:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "Archivo vacio"}), 400

    # Validate size (500KB max)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 512000:
        return (
            jsonify(success=False, error={"code": "FILE_TOO_LARGE", "message": "El logo debe ser menor a 500 KB"}),
            400,
        )

    # Validate MIME type
    allowed_types = {"image/png", "image/jpeg", "image/svg+xml", "image/webp"}
    if file.content_type not in allowed_types:
        return (
            jsonify(
                success=False,
                error={"code": "INVALID_TYPE", "message": "Formato no soportado. Use PNG, JPG, SVG o WebP."},
            ),
            400,
        )

    import base64
    import io

    # For raster images, resize if too large
    if file.content_type in ("image/png", "image/jpeg", "image/webp"):
        from PIL import Image

        img = Image.open(file)
        max_size = 200
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "PNG" if file.content_type != "image/jpeg" else "JPEG"
        img.save(buf, format=fmt, quality=85, optimize=True)
        img_bytes = buf.getvalue()
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
    else:
        # SVG — store as-is
        img_bytes = file.read()
        mime = file.content_type

    data_uri = f"data:{mime};base64,{base64.b64encode(img_bytes).decode('utf-8')}"

    try:
        tenant = update_tenant(g.tenant_id, logo_url=data_uri)
        return jsonify(success=True, data={"logo_url": tenant["logo_url"]})
    except ValueError as e:
        return jsonify(success=False, error={"code": "UPLOAD_ERROR", "message": str(e)}), 500


# ── Roles & Permissions ───────────────────────────────────────────


@auth_bp.route("/roles", methods=["GET"])
@require_permission("roles", "manage")
def list_roles():
    from flask import g

    data = get_tenant_roles(g.tenant_id)
    return jsonify(success=True, data=data)


@auth_bp.route("/roles", methods=["POST"])
@require_permission("roles", "manage")
def create_role():
    from flask import g

    data = request.get_json()
    if not data.get("name") or not data.get("permission_ids"):
        return (
            jsonify(
                success=False, error={"code": "VALIDATION_ERROR", "message": "name y permission_ids son requeridos"}
            ),
            400,
        )
    try:
        role = create_custom_role(g.tenant_id, data["name"], data["permission_ids"])
        return jsonify(success=True, data=role), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "ROLE_ERROR", "message": str(e)}), 400


@auth_bp.route("/roles/<role_id>/permissions", methods=["PUT"])
@require_permission("roles", "manage")
def update_role_perms(role_id):
    from flask import g

    data = request.get_json()
    if not data.get("permission_ids"):
        return jsonify(success=False, error={"code": "VALIDATION_ERROR", "message": "permission_ids es requerido"}), 400
    try:
        role = update_role_permissions(g.tenant_id, role_id, data["permission_ids"])
        return jsonify(success=True, data=role)
    except ValueError as e:
        return jsonify(success=False, error={"code": "ROLE_ERROR", "message": str(e)}), 400


@auth_bp.route("/roles/reset-defaults", methods=["POST"])
@require_permission("roles", "manage")
def reset_role_defaults():
    """Reset all system roles to their default permissions."""
    from app.modules.auth_rbac.services import seed_roles_and_permissions

    seed_roles_and_permissions()
    return jsonify(success=True, data={"message": "Permisos restaurados a valores por defecto"})


@auth_bp.route("/permissions", methods=["GET"])
@require_permission("roles", "manage")
def list_perms_grouped():
    data = list_permissions_grouped()
    return jsonify(success=True, data=data)


# ── Users ─────────────────────────────────────────────────────────


@auth_bp.route("/users", methods=["GET"])
@require_permission("users", "read")
def list_users():
    """List all users in the current tenant."""
    from flask import g

    users = get_users_by_tenant(g.tenant_id)
    return jsonify(success=True, data=users)


@auth_bp.route("/users", methods=["POST"])
@require_permission("users", "create")
def add_user():
    """Create a new user in the current tenant."""
    from flask import g

    data = request.get_json()
    required = ["email", "password", "first_name", "last_name"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return (
            jsonify(
                success=False,
                error={
                    "code": "VALIDATION_ERROR",
                    "message": f"Campos requeridos: {', '.join(missing)}",
                },
            ),
            400,
        )

    try:
        user = create_user(
            tenant_id=g.tenant_id,
            email=data["email"],
            password=data["password"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            role_name=data.get("role", "cashier"),
        )
        return jsonify(success=True, data=user), 201
    except ValueError as e:
        return jsonify(success=False, error={"code": "USER_CREATE_ERROR", "message": str(e)}), 409


@auth_bp.route("/users/<user_id>", methods=["PATCH"])
@require_permission("users", "update")
def edit_user(user_id):
    """Update a user's info or role."""
    from flask import g

    data = request.get_json()
    try:
        user = update_user(g.tenant_id, user_id, **data)
        return jsonify(success=True, data=user)
    except ValueError as e:
        return jsonify(success=False, error={"code": "USER_UPDATE_ERROR", "message": str(e)}), 400


@auth_bp.route("/users/<user_id>/deactivate", methods=["POST"])
@require_permission("users", "delete")
def toggle_user(user_id):
    """Activate/deactivate a user."""
    from flask import g

    try:
        user = deactivate_user(g.tenant_id, user_id)
        status = "activado" if user["is_active"] else "desactivado"
        return jsonify(success=True, data=user, message=f"Usuario {status}")
    except ValueError as e:
        return jsonify(success=False, error={"code": "USER_DEACTIVATE_ERROR", "message": str(e)}), 400


@auth_bp.route("/users/<user_id>/reset-password", methods=["POST"])
@require_permission("users", "update")
def reset_password(user_id):
    """Reset a user's password."""
    from flask import g

    data = request.get_json()
    password = data.get("password", "")
    try:
        user = reset_user_password(g.tenant_id, user_id, password)
        return jsonify(success=True, data=user)
    except ValueError as e:
        return jsonify(success=False, error={"code": "PASSWORD_RESET_ERROR", "message": str(e)}), 400


@auth_bp.route("/tenant/test-smtp", methods=["POST"])
@require_permission("tenants", "manage")
def test_smtp():
    """Send a test email to verify SMTP configuration."""
    from flask import g

    from app.core.email_service import send_email
    from app.modules.auth_rbac.models import Tenant

    tenant = Tenant.query.get(g.tenant_id)
    if not tenant or not tenant.smtp_host:
        return (
            jsonify(
                success=False,
                error={
                    "code": "SMTP_NOT_CONFIGURED",
                    "message": "Configure el servidor SMTP primero en la sección de Notificaciones.",
                },
            ),
            400,
        )

    # Send test email to tenant's email
    to_email = tenant.email or tenant.smtp_user
    result = send_email(
        smtp_host=tenant.smtp_host,
        smtp_port=tenant.smtp_port or 587,
        smtp_user=tenant.smtp_user,
        smtp_password=tenant.smtp_password,
        from_email=tenant.smtp_from_email or tenant.smtp_user,
        to_email=to_email,
        subject=f"ROHU - Prueba de correo ({tenant.name})",
        body_html=f"""
        <div style="font-family:Arial; max-width:500px; margin:0 auto; padding:20px;">
            <div style="background:#1E3A8A; color:white; padding:16px; border-radius:8px 8px 0 0; text-align:center;">
                <h2 style="margin:0;">ROHU Contable</h2>
            </div>
            <div style="border:1px solid #E2E8F0; padding:20px; border-radius:0 0 8px 8px;">
                <h3 style="color:#10B981;">Prueba exitosa</h3>
                <p>Este es un correo de prueba enviado desde <strong>{tenant.name}</strong>.</p>
                <p>Si recibes este mensaje, tu configuración SMTP está funcionando correctamente.</p>
                <hr style="border:none; border-top:1px solid #E2E8F0; margin:16px 0;">
                <p style="font-size:12px; color:#64748B;">
                    Servidor: {tenant.smtp_host}:{tenant.smtp_port}<br>
                    Remitente: {tenant.smtp_from_email or tenant.smtp_user}
                </p>
            </div>
        </div>
        """,
    )

    if result["success"]:
        return jsonify(
            success=True,
            data={
                "message": f"Correo de prueba enviado a {to_email}",
                "to": to_email,
            },
        )
    else:
        return (
            jsonify(
                success=False,
                error={"code": "SMTP_SEND_FAILED", "message": result.get("error", "Error desconocido al enviar")},
            ),
            400,
        )


@auth_bp.route("/tenant/reset", methods=["POST"])
@require_permission("tenants", "manage")
def reset_data():
    """Reset all transactional data for the tenant."""
    from flask import g

    data = request.get_json() or {}
    if data.get("confirm") != "REINICIAR":
        return (
            jsonify(
                success=False,
                error={"code": "CONFIRMATION_REQUIRED", "message": 'Envíe {"confirm": "REINICIAR"} para confirmar'},
            ),
            400,
        )
    try:
        result = reset_tenant_data(g.tenant_id)
        return jsonify(success=True, data=result)
    except Exception as e:
        return jsonify(success=False, error={"code": "RESET_ERROR", "message": str(e)}), 500


@auth_bp.route("/saas-clients", methods=["GET"])
@require_permission("tenants", "manage")
def list_saas_clients():
    """List all deployed ROHU SaaS client instances from clients.json."""
    import json
    import os

    clients_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "clients.json"
    )
    try:
        with open(clients_file, "r") as f:
            clients = json.load(f)
        return jsonify(success=True, data=clients)
    except FileNotFoundError:
        return jsonify(success=True, data=[])
    except Exception as e:
        return jsonify(success=False, error={"code": "FILE_ERROR", "message": str(e)}), 500


@auth_bp.route("/sync-status", methods=["GET"])
@require_permission("tenants", "manage")
def sync_status():
    """Check sync status of all replicas by comparing their /health deployed_at with this app's."""
    import json
    import os

    import requests as http

    # Get this app's deploy time from health endpoint
    main_version = "1.2.3"
    main_deployed = os.getenv("DEPLOY_TIME", "")

    clients_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "clients.json"
    )
    try:
        with open(clients_file, "r") as f:
            clients = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        clients = []

    results = []
    for c in clients:
        app_name = c.get("app", "")
        url = c.get("url", "").rstrip("/")
        health_url = f"{url}/health" if url else f"https://{app_name}.herokuapp.com/health"

        entry = {
            "name": c.get("name", app_name),
            "app": app_name,
            "url": url,
            "admin_email": c.get("admin_email", ""),
            "created_at": c.get("created_at", ""),
        }

        try:
            resp = http.get(health_url, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                replica_version = data.get("version", "")
                replica_deployed = data.get("deployed_at", "")
                entry["status"] = "online"
                entry["version"] = replica_version
                entry["deployed_at"] = replica_deployed
                # Synced if same version AND deployed after or same as main
                if replica_version == main_version:
                    if main_deployed and replica_deployed:
                        entry["synced"] = replica_deployed >= main_deployed
                    else:
                        entry["synced"] = True
                else:
                    entry["synced"] = False
            else:
                entry["status"] = "error"
                entry["synced"] = False
        except Exception:
            entry["status"] = "offline"
            entry["synced"] = False

        results.append(entry)

    return jsonify(success=True, data={"main_version": main_version, "clients": results})


@auth_bp.route("/deploy-all", methods=["POST"])
@require_permission("tenants", "manage")
def deploy_all():
    """Trigger deployment to all SaaS client replicas via Heroku Build API."""
    data = request.get_json() or {}
    if data.get("confirm") != "DEPLOY":
        return (
            jsonify(
                success=False,
                error={"code": "CONFIRMATION_REQUIRED", "message": 'Envíe {"confirm": "DEPLOY"} para confirmar'},
            ),
            400,
        )

    try:
        from app.modules.auth_rbac.deploy_service import start_deploy_all

        state = start_deploy_all()
        return jsonify(success=True, data=state), 202
    except ValueError as e:
        return jsonify(success=False, error={"code": "DEPLOY_ERROR", "message": str(e)}), 409
    except Exception as e:
        return jsonify(success=False, error={"code": "DEPLOY_ERROR", "message": str(e)}), 500


@auth_bp.route("/deploy-status", methods=["GET"])
@require_permission("tenants", "manage")
def deploy_status():
    """Get current deployment status (for polling)."""
    from app.modules.auth_rbac.deploy_service import get_deploy_status

    return jsonify(success=True, data=get_deploy_status())


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    """Get current user profile."""
    identity = get_jwt_identity()
    from app.modules.auth_rbac.models import User

    user = User.query.get(identity["user_id"])
    if not user:
        return jsonify(success=False, error={"code": "AUTH_INVALID_TOKEN", "message": "Usuario no encontrado"}), 401

    from app.modules.auth_rbac.services import _tenant_to_dict, _user_to_dict

    return jsonify(
        success=True,
        data={
            "user": _user_to_dict(user),
            "tenant": _tenant_to_dict(user.tenant),
            "permissions": list(user.permission_set),
        },
    )
