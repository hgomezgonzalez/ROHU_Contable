#!/usr/bin/env bash
set -e

echo "--- Running Alembic migrations ---"
flask db upgrade

echo "--- Seeding roles and permissions ---"
flask seed

echo "--- Release phase completed ---"
