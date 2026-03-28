"""Cash blueprint definition."""

from flask import Blueprint

cash_bp = Blueprint("cash", __name__, url_prefix="/api/v1/cash")

from app.modules.cash import routes  # noqa: F401, E402
