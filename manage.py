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


@cli.command("init-db")
def init_db():
    """Create all database tables."""
    from app.extensions import db
    db.create_all()
    click.echo("Database tables created.")


if __name__ == "__main__":
    cli()
