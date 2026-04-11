#!/usr/bin/env bash
# ROHU Contable — Create a new client replica on Heroku.
#
# Usage:
#   ./scripts/add-client.sh <business_name> <nit> <admin_email> <admin_password>
#
# Example:
#   ./scripts/add-client.sh "Ferreteria Ramirez" "900123456" "ramirez@email.com" "SecurePass123"
#
# NEW MODEL (from 2026-04):
#   - ONE shared Postgres + ONE shared Redis (provisioned on rohu-shared-db).
#   - Each new SaaS client gets its own Heroku app (the "replica"),
#     BUT instead of a dedicated database, it gets a dedicated Postgres SCHEMA
#     inside the shared DB.
#   - DATABASE_URL and REDIS_URL are copied from rohu-shared-db so every
#     replica points to the same cluster.
#   - DB_SCHEMA is set per replica (rohu_<slug>) and everything the app does
#     (migrations, seeds, queries) is isolated to that schema.

set -e

# --- Validate arguments ---
if [ $# -lt 4 ]; then
  echo ""
  echo "Usage: ./scripts/add-client.sh <business_name> <nit> <admin_email> <admin_password>"
  echo ""
  echo "Example:"
  echo "  ./scripts/add-client.sh 'Ferreteria Ramirez' '900123456' 'ramirez@email.com' 'SecurePass123'"
  echo ""
  exit 1
fi

BUSINESS_NAME="$1"
NIT="$2"
ADMIN_EMAIL="$3"
ADMIN_PASSWORD="$4"

# Heroku app name (kebab-case, max 30 chars).
APP_SLUG=$(echo "$BUSINESS_NAME" \
  | tr '[:upper:]' '[:lower:]' \
  | sed 's/[^a-z0-9]/-/g' \
  | sed 's/--*/-/g' \
  | sed 's/^-//' \
  | sed 's/-$//' \
  | cut -c1-25)
APP_NAME="rohu-${APP_SLUG}"

# Postgres schema name (snake_case, same semantic slug as the app).
SCHEMA_SLUG=$(echo "$APP_SLUG" | tr '-' '_')
SCHEMA_NAME="rohu_${SCHEMA_SLUG}"

# Source of truth for the shared infra. Must already exist and expose
# DATABASE_URL + REDIS_URL config vars (or REDIS_TLS_URL for TLS).
SHARED_DB_APP="${SHARED_DB_APP:-rohu-shared-db}"

echo ""
echo "========================================="
echo "  ROHU Contable — Nueva replica de cliente"
echo "========================================="
echo "  Negocio:  $BUSINESS_NAME"
echo "  NIT:      $NIT"
echo "  Admin:    $ADMIN_EMAIL"
echo "  App:      $APP_NAME"
echo "  Schema:   $SCHEMA_NAME"
echo "  DB infra: $SHARED_DB_APP (compartida)"
echo "========================================="
echo ""

# --- Check Heroku CLI ---
if ! command -v heroku &> /dev/null; then
  echo "ERROR: Heroku CLI no esta instalado. Instalalo: curl https://cli-assets.heroku.com/install.sh | sh"
  exit 1
fi

# --- 1. Create Heroku app (NO postgres addon — DB is shared) ---
echo "[1/6] Creando app Heroku: $APP_NAME..."
heroku create "$APP_NAME" || {
  echo "ERROR: No se pudo crear la app. El nombre '$APP_NAME' puede estar en uso."
  exit 1
}

# --- 2. Buildpacks (apt for tesseract, then python) ---
echo "[2/6] Configurando buildpacks..."
heroku buildpacks:add --index 1 https://github.com/heroku/heroku-buildpack-apt --app "$APP_NAME"
heroku buildpacks:add --index 2 heroku/python --app "$APP_NAME"

# --- 3. Pull shared infra URLs from SHARED_DB_APP ---
echo "[3/6] Leyendo DATABASE_URL y REDIS_URL compartidas desde $SHARED_DB_APP..."
SHARED_DB_URL=$(heroku config:get DATABASE_URL --app "$SHARED_DB_APP")
SHARED_REDIS_URL=$(heroku config:get REDIS_TLS_URL --app "$SHARED_DB_APP")
if [ -z "$SHARED_REDIS_URL" ]; then
  SHARED_REDIS_URL=$(heroku config:get REDIS_URL --app "$SHARED_DB_APP")
fi

if [ -z "$SHARED_DB_URL" ]; then
  echo "ERROR: No se pudo leer DATABASE_URL de $SHARED_DB_APP."
  exit 1
fi

# --- 4. Config vars on the new replica ---
echo "[4/6] Configurando variables de entorno..."
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

heroku config:set \
  FLASK_APP="app:create_app" \
  FLASK_ENV="production" \
  DEBUG="False" \
  DATABASE_URL="$SHARED_DB_URL" \
  REDIS_URL="$SHARED_REDIS_URL" \
  DB_SCHEMA="$SCHEMA_NAME" \
  SECRET_KEY="$SECRET_KEY" \
  JWT_SECRET_KEY="$JWT_SECRET_KEY" \
  JWT_ACCESS_TOKEN_EXPIRES="900" \
  JWT_REFRESH_TOKEN_EXPIRES="2592000" \
  TIMEZONE="America/Bogota" \
  LOCALE="es-CO" \
  CURRENCY="COP" \
  TESSDATA_PREFIX="/app/.apt/usr/share/tesseract-ocr/5/tessdata/" \
  HEROKU_APP_NAME="$APP_NAME" \
  --app "$APP_NAME"

# --- 5. Deploy code from GitHub main (same source as all replicas) ---
echo "[5/6] Desplegando codigo..."
git remote add "$APP_SLUG" "https://git.heroku.com/${APP_NAME}.git" 2>/dev/null || true
git push "$APP_SLUG" main
# release.sh will run `flask db upgrade` which creates the schema and seeds.

# --- 6. Create admin user + update clients.json ---
echo "[6/6] Creando usuario administrador y actualizando registry..."
heroku run "python manage.py create-admin \
  --name '$BUSINESS_NAME' \
  --nit '$NIT' \
  --email '$ADMIN_EMAIL' \
  --first-name 'Admin' \
  --last-name '$BUSINESS_NAME' \
  --admin-email '$ADMIN_EMAIL' \
  --password '$ADMIN_PASSWORD'" --app "$APP_NAME"

APP_URL=$(heroku info -s --app "$APP_NAME" | grep web_url | cut -d= -f2 | tr -d '\n')
TODAY=$(date +%Y-%m-%d)

python3 -c "
import json
with open('clients.json', 'r') as f:
    clients = json.load(f)
clients.append({
    'name': '$BUSINESS_NAME',
    'app': '$APP_NAME',
    'schema': '$SCHEMA_NAME',
    'url': '${APP_URL}',
    'admin_email': '$ADMIN_EMAIL',
    'created_at': '$TODAY'
})
with open('clients.json', 'w') as f:
    json.dump(clients, f, indent=2, ensure_ascii=False)
print(f'Registered replica #{len(clients)} in clients.json')
"

echo ""
echo "========================================="
echo "  REPLICA CREADA EXITOSAMENTE"
echo "========================================="
echo "  URL:    ${APP_URL}"
echo "  Schema: $SCHEMA_NAME"
echo "  Admin:  $ADMIN_EMAIL"
echo ""
echo "  Acceso: ${APP_URL}app/login"
echo "========================================="
echo ""
echo "No olvides hacer commit de clients.json:"
echo "  git add clients.json && git commit -m 'feat: add client $BUSINESS_NAME' && git push origin main"
