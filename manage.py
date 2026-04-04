"""CLI management commands for ROHU Contable."""

import click
from flask.cli import FlaskGroup

from app import create_app


def _create_app():
    import os
    return create_app(os.getenv("FLASK_ENV", "development"))


@click.group(cls=FlaskGroup, create_app=_create_app)
def cli():
    """ROHU Contable management CLI."""
    pass


@cli.command("seed")
def seed():
    """Seed system roles and permissions."""
    from app.modules.auth_rbac.services import seed_roles_and_permissions
    seed_roles_and_permissions()
    click.echo("Roles and permissions seeded successfully.")


@cli.command("create-admin")
@click.option("--name", prompt="Nombre del negocio")
@click.option("--nit", prompt="NIT")
@click.option("--email", prompt="Email del negocio")
@click.option("--first-name", prompt="Nombre del admin")
@click.option("--last-name", prompt="Apellido del admin")
@click.option("--admin-email", prompt="Email del admin")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin(name, nit, email, first_name, last_name, admin_email, password):
    """Create first tenant and admin user."""
    from app.modules.auth_rbac.services import create_tenant
    from app.modules.accounting.services import seed_chart_of_accounts
    result = create_tenant(
        name=name, tax_id=nit, email=email,
        owner_first_name=first_name, owner_last_name=last_name,
        owner_email=admin_email, owner_password=password,
    )
    tenant_id = result["tenant"]["id"]
    seed_chart_of_accounts(tenant_id)
    click.echo(f"Tenant '{name}' creado con admin {admin_email}")
    click.echo(f"PUC colombiano sembrado ({tenant_id})")


@cli.command("seed-puc")
def seed_puc():
    """Seed PUC (chart of accounts) for all tenants that don't have accounts yet."""
    from app.modules.auth_rbac.models import Tenant
    from app.modules.accounting.models import ChartOfAccount
    from app.modules.accounting.services import seed_chart_of_accounts
    tenants = Tenant.query.filter_by(is_active=True).all()
    for t in tenants:
        count_before = ChartOfAccount.query.filter_by(tenant_id=t.id).count()
        added = seed_chart_of_accounts(str(t.id))
        count_after = ChartOfAccount.query.filter_by(tenant_id=t.id).count()
        click.echo(f"'{t.name}': {count_before} existentes, {added} agregadas, {count_after} total.")
    click.echo("Done.")


@cli.command("init-db")
def init_db():
    """Create all database tables."""
    from app.extensions import db
    db.create_all()
    click.echo("Database tables created.")


if __name__ == "__main__":
    cli()
