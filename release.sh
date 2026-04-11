#!/usr/bin/env bash
set -e

echo "--- Release phase for $HEROKU_APP_NAME (schema: ${DB_SCHEMA:-public}) ---"
echo "--- Running Alembic migrations ---"
flask db upgrade

echo "--- Seeding roles and permissions ---"
python manage.py seed

echo "--- Seeding PUC for all tenants (idempotent) ---"
python manage.py seed-puc

echo "--- Release phase completed ---"
