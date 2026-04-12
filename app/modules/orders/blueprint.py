"""Orders blueprint registration."""

from flask import Blueprint

orders_bp = Blueprint("orders", __name__, url_prefix="/api/v1/orders")

from app.modules.orders import routes  # noqa: F401, E402
