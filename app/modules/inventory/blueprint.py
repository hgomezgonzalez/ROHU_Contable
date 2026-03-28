"""Inventory blueprint registration."""

from flask import Blueprint

inventory_bp = Blueprint("inventory", __name__, url_prefix="/api/v1/inventory")

from app.modules.inventory import routes  # noqa: F401, E402
