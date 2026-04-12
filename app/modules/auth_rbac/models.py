"""Auth RBAC models — Tenants, Users, Roles, Permissions."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


# ── Association tables ────────────────────────────────────────────

role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", UUID(as_uuid=True), db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    db.Column(
        "permission_id", UUID(as_uuid=True), db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    ),
    db.Column("granted_at", db.DateTime(timezone=True), default=_now, nullable=False),
)

user_roles = db.Table(
    "user_roles",
    db.Column("user_id", UUID(as_uuid=True), db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", UUID(as_uuid=True), db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tenant_id", UUID(as_uuid=True), db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
    db.Column("granted_at", db.DateTime(timezone=True), default=_now, nullable=False),
)


# ── Tenant ────────────────────────────────────────────────────────


class Tenant(db.Model):
    """A business subscribed to ROHU. Root of multi-tenant isolation."""

    __tablename__ = "tenants"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name = db.Column(db.String(255), nullable=False)
    trade_name = db.Column(db.String(255))
    tax_id = db.Column(db.String(20), nullable=False, unique=True)
    tax_id_check_digit = db.Column(db.String(1))
    fiscal_regime = db.Column(db.String(50), nullable=False, default="simplified")
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(30))
    address = db.Column(db.String(500))
    city = db.Column(db.String(100))
    country_code = db.Column(db.String(2), nullable=False, default="CO")
    plan_type = db.Column(db.String(30), nullable=False, default="starter")
    max_users = db.Column(db.Integer, nullable=False, default=5)
    currency_code = db.Column(db.String(3), nullable=False, default="COP")
    timezone = db.Column(db.String(50), nullable=False, default="America/Bogota")
    logo_url = db.Column(db.Text)
    favicon_url = db.Column(db.Text)
    # Orders module config (JSONB)
    orders_config = db.Column(
        db.JSON,
        nullable=False,
        default=lambda: {
            "enabled": False,
            "vertical_type": None,
            "kds_enabled": False,
            "tables_enabled": False,
            "delivery_address_required": False,
            "max_open_orders": 50,
            "trial_started_at": None,
            "addon_active_until": None,
        },
    )
    # DIAN e-invoicing
    dian_resolution_number = db.Column(db.String(50))
    dian_resolution_prefix = db.Column(db.String(10), default="FE")
    pta_provider = db.Column(db.String(50), default="factus")
    pta_api_key = db.Column(db.Text)
    # SMTP for email notifications
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(255))
    smtp_password = db.Column(db.Text)
    smtp_from_email = db.Column(db.String(255))
    # Opening balance confirmation
    opening_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    opening_confirmed_at = db.Column(db.DateTime(timezone=True))
    opening_confirmed_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at = db.Column(db.DateTime(timezone=True))
    version = db.Column(db.Integer, nullable=False, default=1)

    users = db.relationship("User", back_populates="tenant", lazy="dynamic", foreign_keys="[User.tenant_id]")

    __table_args__ = (
        CheckConstraint(
            "fiscal_regime IN ('simplified', 'common', 'simple', 'special')", name="ck_tenants_fiscal_regime"
        ),
        CheckConstraint("plan_type IN ('starter', 'professional', 'enterprise')", name="ck_tenants_plan_type"),
        CheckConstraint("max_users > 0", name="ck_tenants_max_users"),
    )

    def __repr__(self):
        return f"<Tenant {self.name} ({self.tax_id})>"


# ── User ──────────────────────────────────────────────────────────


class User(db.Model):
    """System user scoped to a single tenant."""

    __tablename__ = "users"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    email_verified_at = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_at = db.Column(db.DateTime(timezone=True))
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at = db.Column(db.DateTime(timezone=True))
    version = db.Column(db.Integer, nullable=False, default=1)

    tenant = db.relationship("Tenant", back_populates="users", foreign_keys=[tenant_id])
    roles = db.relationship("Role", secondary=user_roles, back_populates="users", lazy="joined")

    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def permission_set(self):
        """All permissions from all assigned roles."""
        perms = set()
        for role in self.roles:
            for perm in role.permissions:
                perms.add(f"{perm.resource}:{perm.action}")
        return perms

    def has_permission(self, resource: str, action: str) -> bool:
        return f"{resource}:{action}" in self.permission_set

    def __repr__(self):
        return f"<User {self.email}>"


# ── Role ──────────────────────────────────────────────────────────


class Role(db.Model):
    """RBAC role. System roles are shared; tenant roles are custom."""

    __tablename__ = "roles"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_system_role = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    version = db.Column(db.Integer, nullable=False, default=1)

    permissions = db.relationship("Permission", secondary=role_permissions, back_populates="roles", lazy="joined")
    users = db.relationship("User", secondary=user_roles, back_populates="roles")

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    def __repr__(self):
        return f"<Role {self.name}>"


# ── Permission ────────────────────────────────────────────────────


class Permission(db.Model):
    """Atomic system capability. Platform-defined, not per-tenant."""

    __tablename__ = "permissions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    resource = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    module = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    roles = db.relationship("Role", secondary=role_permissions, back_populates="permissions")

    __table_args__ = (UniqueConstraint("resource", "action", name="uq_permissions_resource_action"),)

    def __repr__(self):
        return f"<Permission {self.resource}:{self.action}>"


# ── Refresh Token ─────────────────────────────────────────────────


class RefreshToken(db.Model):
    """Persistent refresh token. Only hash is stored."""

    __tablename__ = "refresh_tokens"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    token_hash = db.Column(db.String(255), nullable=False, unique=True)
    device_name = db.Column(db.String(255))
    ip_address = db.Column(db.String(45))
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    is_revoked = db.Column(db.Boolean, nullable=False, default=False)
    revoked_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    def __repr__(self):
        return f"<RefreshToken user={self.user_id} revoked={self.is_revoked}>"
