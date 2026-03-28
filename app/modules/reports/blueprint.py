"""Reports blueprint registration."""

from flask import Blueprint

reports_bp = Blueprint("reports", __name__, url_prefix="/api/v1/reports")

from app.modules.reports import routes  # noqa: F401, E402
