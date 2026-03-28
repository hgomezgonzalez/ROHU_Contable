"""Accounting blueprint registration."""

from flask import Blueprint

accounting_bp = Blueprint("accounting", __name__, url_prefix="/api/v1/accounting")

from app.modules.accounting import routes  # noqa: F401, E402
