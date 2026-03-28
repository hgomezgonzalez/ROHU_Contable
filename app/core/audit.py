"""Core audit log — Automatic tracking of entity changes across all modules."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import event, inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class AuditLog(db.Model):
    """Generic audit log entry. Records who did what, when, and what changed."""

    __tablename__ = "audit_logs"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(UUID(as_uuid=True), nullable=False)
    changes = db.Column(JSONB, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        db.Index("idx_audit_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        db.Index("idx_audit_tenant_date", "tenant_id", "created_at"),
    )

    def __repr__(self):
        return f"<AuditLog {self.action} {self.entity_type} {self.entity_id}>"


# ── Tracked fields to EXCLUDE from change capture ────────────────

_EXCLUDED_FIELDS = {"password_hash", "token_hash", "pta_api_key", "smtp_password", "version", "updated_at"}


def _get_changes(target):
    """Extract changed fields from a SQLAlchemy model instance."""
    insp = inspect(target)
    changes = {}
    for attr in insp.attrs:
        if attr.key in _EXCLUDED_FIELDS:
            continue
        hist = attr.history
        if hist.has_changes():
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if old != new:
                changes[attr.key] = {
                    "old": str(old) if old is not None else None,
                    "new": str(new) if new is not None else None,
                }
    return changes if changes else None


def _get_tenant_id(target):
    """Extract tenant_id from the model if available."""
    return getattr(target, "tenant_id", None)


def _get_current_user_id():
    """Get the current user ID from Flask g context, if available."""
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, "current_user"):
            return g.current_user.id
    except Exception:
        pass
    return None


def _get_current_ip():
    """Get the current request IP address, if available."""
    try:
        from flask import has_request_context, request
        if has_request_context():
            return request.remote_addr
    except Exception:
        pass
    return None


def write_audit_log(action, target, changes=None, connection=None):
    """Write an audit log entry using a connection-level INSERT.

    This is safe to call inside SQLAlchemy after_insert/after_update events
    because it bypasses the Session and writes directly via the connection.
    """
    tenant_id = _get_tenant_id(target)
    if tenant_id is None:
        return

    entity_id = getattr(target, "id", None)
    if entity_id is None:
        return

    if connection is None:
        return

    import json
    connection.execute(
        AuditLog.__table__.insert().values(
            id=_uuid(),
            tenant_id=tenant_id,
            user_id=_get_current_user_id(),
            action=action,
            entity_type=target.__tablename__,
            entity_id=entity_id,
            changes=changes,
            ip_address=_get_current_ip(),
            created_at=_now(),
        )
    )


# ── SQLAlchemy Event Listeners ───────────────────────────────────

# Models to track automatically. Add model classes here after import.
_tracked_models = []


def track_model(model_class):
    """Register a model class for automatic audit logging."""
    _tracked_models.append(model_class)
    return model_class


def _after_insert(mapper, connection, target):
    """Listener for INSERT events."""
    write_audit_log("CREATE", target, connection=connection)


def _after_update(mapper, connection, target):
    """Listener for UPDATE events."""
    changes = _get_changes(target)
    if changes:
        write_audit_log("UPDATE", target, changes, connection=connection)


def _after_delete(mapper, connection, target):
    """Listener for DELETE events."""
    write_audit_log("DELETE", target, connection=connection)


def init_audit_listeners(app):
    """Initialize audit event listeners for all tracked models.
    Call this in create_app() after all models are imported."""
    from app.modules.auth_rbac.models import Tenant, User
    from app.modules.inventory.models import Product, Category
    from app.modules.pos.models import Sale, CashSession, CreditNote
    from app.modules.purchases.models import Supplier, PurchaseOrder, SupplierPayment
    from app.modules.accounting.models import JournalEntry, AccountingPeriod
    from app.modules.customers.models import Customer
    from app.modules.cash.models import CashReceipt, CashDisbursement, CashTransfer, CashCountDetail  # noqa: F841

    tracked = [
        Tenant, User, Product, Category,
        Sale, CashSession, CreditNote,
        Supplier, PurchaseOrder, SupplierPayment,
        JournalEntry, AccountingPeriod,
        Customer,
        CashReceipt, CashDisbursement,
    ]

    for model in tracked:
        event.listen(model, "after_insert", _after_insert)
        event.listen(model, "after_update", _after_update)
        event.listen(model, "after_delete", _after_delete)
