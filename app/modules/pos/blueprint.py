"""POS blueprint registration."""

from flask import Blueprint

pos_bp = Blueprint("pos", __name__, url_prefix="/api/v1/pos")

from app.modules.pos import routes  # noqa: F401, E402
