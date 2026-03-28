"""Customers blueprint definition."""

from flask import Blueprint

customers_bp = Blueprint("customers", __name__, url_prefix="/api/v1/customers")

from app.modules.customers import routes  # noqa: F401, E402
