"""Purchases blueprint registration."""

from flask import Blueprint

purchases_bp = Blueprint("purchases", __name__, url_prefix="/api/v1/purchases")

from app.modules.purchases import routes  # noqa: F401, E402
