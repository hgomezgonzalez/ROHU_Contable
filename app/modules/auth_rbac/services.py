"""Auth RBAC services — Public interface for the auth module."""

import hashlib
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import g, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.extensions import db
from app.modules.auth_rbac.models import (
    Permission,
    RefreshToken,
    Role,
    Tenant,
    User,
    role_permissions,
    user_roles,
)

ph = PasswordHasher()

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


# ── Password Utilities ────────────────────────────────────────────

def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Tenant Services ───────────────────────────────────────────────

def create_tenant(
    name: str,
    tax_id: str,
    email: str,
    owner_first_name: str,
    owner_last_name: str,
    owner_email: str,
    owner_password: str,
    fiscal_regime: str = "simplified",
    city: str = "",
    phone: str = "",
    address: str = "",
) -> dict:
    """Create a new tenant with its owner user. Returns tenant and user data."""
    if Tenant.query.filter_by(tax_id=tax_id).first():
        raise ValueError("NIT ya registrado")

    tenant = Tenant(
        name=name,
        tax_id=tax_id,
        email=email,
        fiscal_regime=fiscal_regime,
        city=city,
        phone=phone,
        address=address,
    )
    db.session.add(tenant)
    db.session.flush()

    user = User(
        tenant_id=tenant.id,
        email=owner_email,
        password_hash=hash_password(owner_password),
        first_name=owner_first_name,
        last_name=owner_last_name,
    )
    db.session.add(user)
    db.session.flush()

    # Assign admin role (manual insert because user_roles has tenant_id NOT NULL)
    admin_role = Role.query.filter_by(name="admin", is_system_role=True).first()
    if admin_role:
        db.session.execute(
            user_roles.insert().values(
                user_id=user.id, role_id=admin_role.id, tenant_id=tenant.id
            )
        )

    db.session.commit()

    # Refresh to load roles relationship
    db.session.refresh(user)

    return {
        "tenant": _tenant_to_dict(tenant),
        "user": _user_to_dict(user),
    }


# ── Auth Services ─────────────────────────────────────────────────

def authenticate(email: str, password: str, tenant_id: Optional[str] = None) -> dict:
    """Authenticate user. Returns user data or raises ValueError."""
    query = User.query.filter(
        User.email == email.lower().strip(),
        User.is_active.is_(True),
        User.deleted_at.is_(None),
    )
    if tenant_id:
        query = query.filter(User.tenant_id == tenant_id)

    user = query.first()
    if not user:
        raise ValueError("Credenciales inválidas")

    # Check lockout
    if user.locked_at:
        lock_elapsed = (datetime.now(timezone.utc) - user.locked_at).total_seconds()
        if lock_elapsed < LOCKOUT_MINUTES * 60:
            remaining = int(LOCKOUT_MINUTES - lock_elapsed / 60)
            raise ValueError(f"Cuenta bloqueada. Intente en {remaining} minutos")
        user.locked_at = None
        user.failed_login_count = 0

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_at = datetime.now(timezone.utc)
        db.session.commit()
        raise ValueError("Credenciales inválidas")

    # Success
    user.failed_login_count = 0
    user.locked_at = None
    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()

    return _user_to_dict(user)


def create_refresh_token_record(
    user_id: str, tenant_id: str, raw_token: str, ip_address: str = ""
) -> None:
    """Store a hashed refresh token in the database."""
    record = RefreshToken(
        user_id=user_id,
        tenant_id=tenant_id,
        token_hash=hash_token(raw_token),
        ip_address=ip_address,
        expires_at=datetime.now(timezone.utc),
    )
    db.session.add(record)
    db.session.commit()


def revoke_all_user_tokens(user_id: str) -> int:
    """Revoke all active refresh tokens for a user."""
    now = datetime.now(timezone.utc)
    count = RefreshToken.query.filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked.is_(False),
    ).update({"is_revoked": True, "revoked_at": now})
    db.session.commit()
    return count


# ── User Services ─────────────────────────────────────────────────

def create_user(
    tenant_id: str,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    role_name: str = "cashier",
) -> dict:
    """Create a new user within a tenant."""
    existing = User.query.filter_by(
        tenant_id=tenant_id, email=email.lower().strip()
    ).first()
    if existing:
        raise ValueError("Email ya registrado en este negocio")

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        raise ValueError("Negocio no encontrado")

    user_count = User.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).count()
    if user_count >= tenant.max_users:
        raise ValueError(f"Límite de usuarios alcanzado ({tenant.max_users})")

    user = User(
        tenant_id=tenant_id,
        email=email.lower().strip(),
        password_hash=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        must_change_password=True,
    )
    db.session.add(user)
    db.session.flush()

    # Search system roles first, then tenant custom roles
    role = Role.query.filter_by(name=role_name, is_system_role=True).first()
    if not role:
        role = Role.query.filter_by(name=role_name, tenant_id=tenant_id).first()
    if role:
        db.session.execute(
            user_roles.insert().values(
                user_id=user.id, role_id=role.id, tenant_id=tenant_id
            )
        )

    db.session.commit()
    db.session.refresh(user)
    return _user_to_dict(user)


def get_tenant(tenant_id: str) -> dict:
    """Get tenant details."""
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        raise ValueError("Negocio no encontrado")
    return _tenant_to_dict(tenant)


def update_tenant(tenant_id: str, **kwargs) -> dict:
    """Update tenant configuration."""
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        raise ValueError("Negocio no encontrado")

    allowed = {"name", "trade_name", "tax_id", "tax_id_check_digit",
               "fiscal_regime", "email", "phone", "address", "city",
               "country_code", "timezone", "currency_code",
               "logo_url", "favicon_url",
               "dian_resolution_number", "dian_resolution_prefix",
               "pta_provider", "pta_api_key",
               "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from_email"}

    for key, value in kwargs.items():
        if key in allowed and value is not None:
            setattr(tenant, key, value)

    db.session.commit()
    return _tenant_to_dict(tenant)


def get_users_by_tenant(tenant_id: str, include_inactive: bool = False) -> list:
    """List users for a tenant."""
    q = User.query.filter(
        User.tenant_id == tenant_id,
        User.deleted_at.is_(None),
    )
    if not include_inactive:
        q = q.filter(User.is_active.is_(True))
    return [_user_to_dict(u) for u in q.all()]


def update_user(tenant_id: str, user_id: str, **kwargs) -> dict:
    """Update user: name, email, role."""
    user = User.query.filter_by(id=user_id, tenant_id=tenant_id).first()
    if not user:
        raise ValueError("Usuario no encontrado")

    for key in ("first_name", "last_name", "email"):
        if key in kwargs and kwargs[key]:
            setattr(user, key, kwargs[key])

    # Change role if provided
    new_role = kwargs.get("role")
    if new_role:
        role = Role.query.filter_by(name=new_role, is_system_role=True).first()
        if not role:
            role = Role.query.filter_by(name=new_role, tenant_id=tenant_id).first()
        if role:
            # Remove existing roles for this tenant
            db.session.execute(
                user_roles.delete().where(
                    user_roles.c.user_id == user.id,
                    user_roles.c.tenant_id == tenant_id,
                )
            )
            db.session.execute(
                user_roles.insert().values(
                    user_id=user.id, role_id=role.id, tenant_id=tenant_id,
                )
            )

    db.session.commit()
    db.session.refresh(user)
    return _user_to_dict(user)


def deactivate_user(tenant_id: str, user_id: str) -> dict:
    """Deactivate/reactivate a user."""
    user = User.query.filter_by(id=user_id, tenant_id=tenant_id).first()
    if not user:
        raise ValueError("Usuario no encontrado")
    user.is_active = not user.is_active
    db.session.commit()
    return _user_to_dict(user)


def reset_user_password(tenant_id: str, user_id: str, new_password: str) -> dict:
    """Reset a user's password."""
    user = User.query.filter_by(id=user_id, tenant_id=tenant_id).first()
    if not user:
        raise ValueError("Usuario no encontrado")
    if len(new_password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_at = None
    db.session.commit()
    return _user_to_dict(user)


def reset_tenant_data(tenant_id: str) -> dict:
    """Reset ALL transactional data for a tenant.
    Preserves: Tenant, Users, Roles, Permissions, ChartOfAccount, Products, Categories, Suppliers, Customers.
    Deletes: Everything else (sales, purchases, cash, campaigns, invoices, journal entries, etc.)
    """
    from app.modules.pos.models import Sale, SaleItem, Payment, CashSession, CreditNote, CreditNoteItem
    from app.modules.inventory.models import StockMovement, Product
    from app.modules.accounting.models import JournalLine, JournalEntry, AccountingPeriod, Expense
    from app.modules.purchases.models import (
        PurchaseOrderItem, PurchaseOrder, SupplierPayment,
        PurchaseCreditNoteItem, PurchaseCreditNote, PurchaseDebitNote,
    )
    from app.modules.cash.models import CashReceipt, CashDisbursement, CashTransfer, CashCountDetail
    from app.modules.customers.models import (
        CustomerPayment, SalesDebitNote,
        CollectionCampaignItem, CollectionCampaign,
    )
    from app.modules.invoicing.models import ElectronicInvoice
    from app.core.audit import AuditLog

    # 1. Campaigns
    CollectionCampaignItem.query.filter(
        CollectionCampaignItem.campaign_id.in_(
            db.session.query(CollectionCampaign.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    CollectionCampaign.query.filter_by(tenant_id=tenant_id).delete()

    # 2. Customer payments and debit notes
    CustomerPayment.query.filter_by(tenant_id=tenant_id).delete()
    SalesDebitNote.query.filter_by(tenant_id=tenant_id).delete()

    # 3. Cash module
    CashCountDetail.query.filter(
        CashCountDetail.cash_session_id.in_(
            db.session.query(CashSession.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    CashTransfer.query.filter_by(tenant_id=tenant_id).delete()
    CashDisbursement.query.filter_by(tenant_id=tenant_id).delete()
    CashReceipt.query.filter_by(tenant_id=tenant_id).delete()

    # 4. Invoicing
    ElectronicInvoice.query.filter_by(tenant_id=tenant_id).delete()

    # 5. POS: credit notes, payments, sale items, sales, sessions
    CreditNoteItem.query.filter(
        CreditNoteItem.credit_note_id.in_(
            db.session.query(CreditNote.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    CreditNote.query.filter_by(tenant_id=tenant_id).delete()
    Payment.query.filter(
        Payment.sale_id.in_(
            db.session.query(Sale.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    SaleItem.query.filter(
        SaleItem.sale_id.in_(
            db.session.query(Sale.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    Sale.query.filter_by(tenant_id=tenant_id).delete()
    CashSession.query.filter_by(tenant_id=tenant_id).delete()

    # 6. Purchases: NC/ND items, NC, ND, payments, PO items, POs
    PurchaseCreditNoteItem.query.filter(
        PurchaseCreditNoteItem.credit_note_id.in_(
            db.session.query(PurchaseCreditNote.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    PurchaseCreditNote.query.filter_by(tenant_id=tenant_id).delete()
    PurchaseDebitNote.query.filter_by(tenant_id=tenant_id).delete()
    SupplierPayment.query.filter_by(tenant_id=tenant_id).delete()
    PurchaseOrderItem.query.filter(
        PurchaseOrderItem.order_id.in_(
            db.session.query(PurchaseOrder.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    PurchaseOrder.query.filter_by(tenant_id=tenant_id).delete()

    # 7. Accounting: journal lines, entries, periods, expenses
    JournalLine.query.filter(
        JournalLine.entry_id.in_(
            db.session.query(JournalEntry.id).filter_by(tenant_id=tenant_id)
        )
    ).delete(synchronize_session=False)
    JournalEntry.query.filter_by(tenant_id=tenant_id).delete()
    AccountingPeriod.query.filter_by(tenant_id=tenant_id).delete()
    Expense.query.filter_by(tenant_id=tenant_id).delete()

    # 8. Inventory movements
    StockMovement.query.filter_by(tenant_id=tenant_id).delete()

    # 9. Audit logs
    AuditLog.query.filter_by(tenant_id=tenant_id).delete()

    # 10. Delete products, categories, suppliers, customers
    from app.modules.inventory.models import Category
    from app.modules.purchases.models import Supplier
    from app.modules.customers.models import Customer
    Product.query.filter_by(tenant_id=tenant_id).delete()
    Category.query.filter_by(tenant_id=tenant_id).delete()
    Supplier.query.filter_by(tenant_id=tenant_id).delete()
    Customer.query.filter_by(tenant_id=tenant_id).delete()

    db.session.commit()

    return {"message": "Todos los datos eliminados. Solo se conservan usuarios, roles y plan de cuentas (PUC)."}


# ── RBAC Decorator ────────────────────────────────────────────────

def require_permission(resource: str, action: str):
    """Decorator to enforce RBAC on a route."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            identity = get_jwt_identity()
            user = User.query.get(identity["user_id"])
            if not user or not user.is_active:
                return {"success": False, "error": {"code": "AUTH_INVALID_TOKEN", "message": "Usuario no válido"}}, 401
            if not user.has_permission(resource, action):
                return {"success": False, "error": {"code": "AUTH_INSUFFICIENT_PERMISSIONS", "message": "No tiene permisos para esta acción"}}, 403

            g.current_user = user
            g.tenant_id = str(user.tenant_id)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ── Seed Data ─────────────────────────────────────────────────────

# ── Custom Roles Management ───────────────────────────────────────

def list_permissions_grouped() -> list:
    """List all permissions grouped by module for the UI."""
    perms = Permission.query.order_by(Permission.module, Permission.resource, Permission.action).all()
    groups = {}
    for p in perms:
        module = p.module or "other"
        if module not in groups:
            groups[module] = {"module": module, "permissions": []}
        groups[module]["permissions"].append({
            "id": str(p.id),
            "key": f"{p.resource}:{p.action}",
            "resource": p.resource,
            "action": p.action,
            "description": p.description or f"{p.resource} - {p.action}",
        })
    return list(groups.values())


def create_custom_role(tenant_id: str, name: str, permission_ids: list) -> dict:
    """Create a tenant-specific custom role with selected permissions."""
    existing = Role.query.filter_by(tenant_id=tenant_id, name=name).first()
    if existing:
        raise ValueError(f"El rol '{name}' ya existe")

    role = Role(
        name=name,
        description=f"Custom role: {name}",
        is_system_role=False,
        tenant_id=tenant_id,
    )
    perms = Permission.query.filter(Permission.id.in_(permission_ids)).all()
    role.permissions = perms
    db.session.add(role)
    db.session.commit()
    return _role_to_dict(role)


def update_role_permissions(tenant_id: str, role_id: str, permission_ids: list) -> dict:
    """Update permissions for a role (custom or system for this tenant)."""
    role = Role.query.filter_by(id=role_id).first()
    if not role:
        raise ValueError("Rol no encontrado")

    perms = Permission.query.filter(Permission.id.in_(permission_ids)).all()
    role.permissions = perms
    db.session.commit()
    return _role_to_dict(role)


def get_tenant_roles(tenant_id: str) -> list:
    """Get all roles available for a tenant (system + custom)."""
    roles = Role.query.filter(
        db.or_(Role.is_system_role.is_(True), Role.tenant_id == tenant_id)
    ).order_by(Role.is_system_role.desc(), Role.name).all()
    return [_role_to_dict(r) for r in roles]


def _role_to_dict(r: Role) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "is_system_role": r.is_system_role,
        "permissions": [
            {"id": str(p.id), "key": f"{p.resource}:{p.action}", "module": p.module}
            for p in r.permissions
        ],
        "permission_count": len(r.permissions),
    }


def seed_roles_and_permissions() -> None:
    """Seed system roles and permissions. Incremental — adds missing perms and updates roles."""

    # All permissions definition
    perms_data = [
        ("tenants", "manage", "identity"),
        ("users", "create", "identity"),
        ("users", "read", "identity"),
        ("users", "update", "identity"),
        ("users", "delete", "identity"),
        ("roles", "manage", "identity"),
        ("sales", "create", "pos"),
        ("sales", "read", "pos"),
        ("sales", "void", "pos"),
        ("sales", "report", "pos"),
        ("cash_sessions", "manage", "pos"),
        ("credit_sales", "create", "pos"),
        ("inventory", "read", "inventory"),
        ("inventory", "update", "inventory"),
        ("inventory", "manage", "inventory"),
        ("inventory_adjustments", "create", "inventory"),
        ("inventory_adjustments", "approve", "inventory"),
        ("products", "create", "catalog"),
        ("products", "read", "catalog"),
        ("products", "update", "catalog"),
        ("products", "delete", "catalog"),
        ("purchases", "create", "purchases"),
        ("purchases", "read", "purchases"),
        ("purchases", "approve", "purchases"),
        ("supplier_payments", "create", "purchases"),
        ("supplier_payments", "read", "purchases"),
        ("supplier_payments", "void", "purchases"),
        ("purchase_credit_notes", "create", "purchases"),
        ("purchase_credit_notes", "read", "purchases"),
        ("journal_entries", "create", "accounting"),
        ("journal_entries", "read", "accounting"),
        ("journal_entries", "close", "accounting"),
        ("chart_of_accounts", "manage", "accounting"),
        ("reports", "read", "reporting"),
        ("reports", "export", "reporting"),
        ("audit_logs", "read", "audit"),
        ("customers", "create", "customers"),
        ("customers", "read", "customers"),
        ("customers", "update", "customers"),
        ("customers", "delete", "customers"),
        ("customer_payments", "create", "customers"),
        ("customer_payments", "read", "customers"),
        ("cash_receipts", "create", "cash"),
        ("cash_receipts", "read", "cash"),
        ("cash_receipts", "void", "cash"),
        ("cash_disbursements", "create", "cash"),
        ("cash_disbursements", "read", "cash"),
        ("cash_disbursements", "void", "cash"),
        ("cash_disbursements", "approve", "cash"),
        ("cash_transfers", "create", "cash"),
        ("cash_transfers", "read", "cash"),
    ]

    # Upsert permissions (create missing ones)
    perm_objects = {}
    for resource, action, module in perms_data:
        existing = Permission.query.filter_by(resource=resource, action=action).first()
        if existing:
            perm_objects[f"{resource}:{action}"] = existing
        else:
            p = Permission(resource=resource, action=action, module=module)
            db.session.add(p)
            db.session.flush()
            perm_objects[f"{resource}:{action}"] = p

    # Role → permissions mapping
    roles_config = {
        "admin": list(perm_objects.values()),  # Admin gets ALL permissions
        "cashier": [
            perm_objects["sales:create"],
            perm_objects["sales:read"],
            perm_objects["sales:void"],
            perm_objects["cash_sessions:manage"],
            perm_objects["credit_sales:create"],
            perm_objects["products:read"],
            perm_objects["inventory:read"],
            perm_objects["customers:create"],
            perm_objects["customers:read"],
            perm_objects["customer_payments:create"],
            perm_objects["customer_payments:read"],
            perm_objects["cash_receipts:create"],
            perm_objects["cash_receipts:read"],
            perm_objects["cash_receipts:void"],
            perm_objects["cash_transfers:create"],
            perm_objects["cash_transfers:read"],
        ],
        "accountant": [
            perm_objects["journal_entries:create"],
            perm_objects["journal_entries:read"],
            perm_objects["journal_entries:close"],
            perm_objects["chart_of_accounts:manage"],
            perm_objects["reports:read"],
            perm_objects["reports:export"],
            perm_objects["sales:read"],
            perm_objects["audit_logs:read"],
            perm_objects["purchases:read"],
            perm_objects["purchases:create"],
            perm_objects["purchases:approve"],
            perm_objects["supplier_payments:create"],
            perm_objects["supplier_payments:read"],
            perm_objects["supplier_payments:void"],
            perm_objects["purchase_credit_notes:create"],
            perm_objects["purchase_credit_notes:read"],
            perm_objects["customers:create"],
            perm_objects["customers:read"],
            perm_objects["customers:update"],
            perm_objects["customer_payments:create"],
            perm_objects["customer_payments:read"],
            perm_objects["cash_receipts:create"],
            perm_objects["cash_receipts:read"],
            perm_objects["cash_receipts:void"],
            perm_objects["cash_disbursements:create"],
            perm_objects["cash_disbursements:read"],
            perm_objects["cash_disbursements:void"],
            perm_objects["cash_disbursements:approve"],
            perm_objects["cash_transfers:create"],
            perm_objects["cash_transfers:read"],
        ],
        "viewer": [
            perm_objects["sales:read"],
            perm_objects["products:read"],
            perm_objects["inventory:read"],
            perm_objects["purchases:read"],
            perm_objects["journal_entries:read"],
            perm_objects["reports:read"],
            perm_objects["customers:read"],
            perm_objects["customer_payments:read"],
            perm_objects["cash_receipts:read"],
            perm_objects["cash_disbursements:read"],
            perm_objects["cash_transfers:read"],
        ],
    }

    # Upsert roles and update their permissions
    for role_name, perms in roles_config.items():
        role = Role.query.filter_by(name=role_name, is_system_role=True).first()
        if not role:
            role = Role(
                name=role_name,
                description=f"System role: {role_name}",
                is_system_role=True,
                tenant_id=None,
            )
            db.session.add(role)
        # Always update permissions to latest definition
        role.permissions = perms

    db.session.commit()


# ── Serializers ───────────────────────────────────────────────────

def _tenant_to_dict(tenant: Tenant) -> dict:
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "trade_name": tenant.trade_name,
        "tax_id": tenant.tax_id,
        "tax_id_check_digit": tenant.tax_id_check_digit,
        "fiscal_regime": tenant.fiscal_regime,
        "email": tenant.email,
        "phone": tenant.phone,
        "address": tenant.address,
        "city": tenant.city,
        "country_code": tenant.country_code,
        "timezone": tenant.timezone,
        "currency_code": tenant.currency_code,
        "logo_url": tenant.logo_url,
        "favicon_url": tenant.favicon_url,
        "dian_resolution_number": tenant.dian_resolution_number,
        "dian_resolution_prefix": tenant.dian_resolution_prefix,
        "pta_provider": tenant.pta_provider,
        "pta_api_key": "***" if tenant.pta_api_key else None,
        "smtp_host": tenant.smtp_host,
        "smtp_port": tenant.smtp_port,
        "smtp_user": tenant.smtp_user,
        "smtp_password": "***" if tenant.smtp_password else None,
        "smtp_from_email": tenant.smtp_from_email,
        "plan_type": tenant.plan_type,
        "max_users": tenant.max_users,
        "is_active": tenant.is_active,
    }


def _user_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "roles": [r.name for r in user.roles],
    }
