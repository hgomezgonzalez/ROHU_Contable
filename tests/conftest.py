"""Shared pytest fixtures for ROHU Contable tests."""

import uuid

import pytest
from flask_jwt_extended import create_access_token

from app import create_app
from app.extensions import db as _db
from app.modules.auth_rbac.models import (
    Permission,
    Role,
    Tenant,
    User,
    role_permissions,
    user_roles,
)
from app.modules.auth_rbac.services import hash_password, seed_roles_and_permissions


@pytest.fixture(scope="session")
def app():
    """Create the Flask application for the test session."""
    application = create_app("testing")
    with application.app_context():
        yield application


@pytest.fixture(scope="session")
def _setup_db(app):
    """Create all tables once per test session."""
    with app.app_context():
        _db.create_all()
        seed_roles_and_permissions()
        yield
        _db.drop_all()


@pytest.fixture(autouse=True)
def db_session(app, _setup_db):
    """Provide a clean database session for each test.

    Uses savepoints so each test runs in an isolated sub-transaction
    that is rolled back after the test, keeping the session-scoped
    schema and seed data intact.
    """
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin_nested()  # SAVEPOINT

        # Bind the global session to this connection
        _db.session.configure(bind=connection)

        yield _db.session

        _db.session.rollback()
        _db.session.remove()
        connection.close()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def tenant(db_session):
    """Create a test tenant."""
    t = Tenant(
        name="Ferretería Test",
        tax_id=f"TEST-{uuid.uuid4().hex[:8]}",
        email="test@rohu.co",
        fiscal_regime="simplified",
        city="Bogotá",
    )
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture
def admin_user(db_session, tenant):
    """Create an admin user for the test tenant."""
    user = User(
        tenant_id=tenant.id,
        email="admin@test.co",
        password_hash=hash_password("Test1234!"),
        first_name="Admin",
        last_name="Test",
    )
    db_session.add(user)
    db_session.flush()

    admin_role = Role.query.filter_by(name="admin", is_system_role=True).first()
    if admin_role:
        db_session.execute(user_roles.insert().values(user_id=user.id, role_id=admin_role.id, tenant_id=tenant.id))
        db_session.flush()
    db_session.refresh(user)
    return user


@pytest.fixture
def cashier_user(db_session, tenant):
    """Create a cashier user for the test tenant."""
    user = User(
        tenant_id=tenant.id,
        email="cajero@test.co",
        password_hash=hash_password("Test1234!"),
        first_name="Cajero",
        last_name="Test",
    )
    db_session.add(user)
    db_session.flush()

    cashier_role = Role.query.filter_by(name="cashier", is_system_role=True).first()
    if cashier_role:
        db_session.execute(user_roles.insert().values(user_id=user.id, role_id=cashier_role.id, tenant_id=tenant.id))
        db_session.flush()
    db_session.refresh(user)
    return user


@pytest.fixture
def accountant_user(db_session, tenant):
    """Create an accountant user for the test tenant."""
    user = User(
        tenant_id=tenant.id,
        email="contador@test.co",
        password_hash=hash_password("Test1234!"),
        first_name="Contador",
        last_name="Test",
    )
    db_session.add(user)
    db_session.flush()

    accountant_role = Role.query.filter_by(name="accountant", is_system_role=True).first()
    if accountant_role:
        db_session.execute(user_roles.insert().values(user_id=user.id, role_id=accountant_role.id, tenant_id=tenant.id))
        db_session.flush()
    db_session.refresh(user)
    return user


@pytest.fixture
def viewer_user(db_session, tenant):
    """Create a viewer user for the test tenant."""
    user = User(
        tenant_id=tenant.id,
        email="viewer@test.co",
        password_hash=hash_password("Test1234!"),
        first_name="Viewer",
        last_name="Test",
    )
    db_session.add(user)
    db_session.flush()

    viewer_role = Role.query.filter_by(name="viewer", is_system_role=True).first()
    if viewer_role:
        db_session.execute(user_roles.insert().values(user_id=user.id, role_id=viewer_role.id, tenant_id=tenant.id))
        db_session.flush()
    db_session.refresh(user)
    return user


def _auth_headers(user):
    """Generate JWT auth headers for a user."""
    token = create_access_token(identity={"user_id": str(user.id), "tenant_id": str(user.tenant_id)})
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def admin_headers(admin_user):
    """Auth headers for admin user."""
    return _auth_headers(admin_user)


@pytest.fixture
def cashier_headers(cashier_user):
    """Auth headers for cashier user."""
    return _auth_headers(cashier_user)


@pytest.fixture
def accountant_headers(accountant_user):
    """Auth headers for accountant user."""
    return _auth_headers(accountant_user)


@pytest.fixture
def viewer_headers(viewer_user):
    """Auth headers for viewer user."""
    return _auth_headers(viewer_user)


@pytest.fixture
def sample_product(db_session, tenant, admin_user):
    """Create a sample product for testing."""
    from app.modules.inventory.models import Product

    product = Product(
        tenant_id=tenant.id,
        created_by=admin_user.id,
        name="Martillo Stanley",
        sku="MART-001",
        qr_code=f"QR-{uuid.uuid4().hex[:8]}",
        sale_price=25000,
        purchase_price=15000,
        cost_average=15000,
        stock_current=50,
        stock_minimum=5,
        tax_type="iva_19",
        tax_rate=19.0,
    )
    db_session.add(product)
    db_session.flush()
    return product


@pytest.fixture
def wholesale_product(db_session, tenant, admin_user):
    """Create a product with wholesale pricing configured."""
    from decimal import Decimal

    from app.modules.inventory.models import Product

    product = Product(
        tenant_id=tenant.id,
        created_by=admin_user.id,
        name="Cemento Argos x50kg",
        sku="CEM-50KG",
        qr_code=f"QR-WHL-{uuid.uuid4().hex[:8]}",
        sale_price=Decimal("35000"),
        wholesale_price=Decimal("28000"),
        wholesale_min_qty=Decimal("10"),
        purchase_price=Decimal("22000"),
        cost_average=Decimal("22000"),
        stock_current=Decimal("200"),
        stock_minimum=Decimal("5"),
        tax_type="iva_19",
        tax_rate=Decimal("19.0"),
    )
    db_session.add(product)
    db_session.flush()
    return product


@pytest.fixture
def retail_only_product(db_session, tenant, admin_user):
    """Create a product WITHOUT wholesale pricing — for fallback tests."""
    from decimal import Decimal

    from app.modules.inventory.models import Product

    product = Product(
        tenant_id=tenant.id,
        created_by=admin_user.id,
        name="Puntilla 2 pulgadas",
        sku="PNT-2IN",
        qr_code=f"QR-RTL-{uuid.uuid4().hex[:8]}",
        sale_price=Decimal("500"),
        wholesale_price=None,
        wholesale_min_qty=None,
        purchase_price=Decimal("250"),
        cost_average=Decimal("250"),
        stock_current=Decimal("1000"),
        stock_minimum=Decimal("10"),
        tax_type="iva_19",
        tax_rate=Decimal("19.0"),
    )
    db_session.add(product)
    db_session.flush()
    return product
