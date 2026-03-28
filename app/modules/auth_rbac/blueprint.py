"""Auth RBAC blueprint registration."""

from flask import Blueprint

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

# Import routes to register them with the blueprint
from app.modules.auth_rbac import routes  # noqa: F401, E402
