#!/usr/bin/env bash
set -e

echo "--- Running Alembic migrations ---"
flask db upgrade

echo "--- Seeding roles and permissions ---"
python manage.py seed

echo "--- Starting Gunicorn ---"
exec gunicorn "app:create_app()" \
  --bind 0.0.0.0:${PORT:-5000} \
  --workers ${WORKERS:-3} \
  --worker-class gthread \
  --threads 4 \
  --timeout 30 \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --access-logfile -
