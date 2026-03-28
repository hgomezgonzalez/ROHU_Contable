"""Invoicing blueprint registration."""

from flask import Blueprint

invoicing_bp = Blueprint("invoicing", __name__, url_prefix="/api/v1/invoicing")

from app.modules.invoicing import routes  # noqa: F401, E402
