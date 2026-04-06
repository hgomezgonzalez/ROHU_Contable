"""Vouchers blueprint registration."""

from flask import Blueprint

vouchers_bp = Blueprint("vouchers", __name__, url_prefix="/api/v1/vouchers")

from app.modules.vouchers import routes  # noqa: F401, E402
