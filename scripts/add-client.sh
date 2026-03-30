#!/usr/bin/env bash
# ROHU Contable — Create a new client instance on Heroku
# Usage: ./scripts/add-client.sh "Nombre Negocio" "NIT" "email@admin.com" "password"
#
# This script:
# 1. Creates a new Heroku app with a unique name
# 2. Adds PostgreSQL addon
# 3. Sets config vars (SECRET_KEY, JWT, etc.)
# 4. Deploys the code
# 5. Runs migrations and seeds
# 6. Creates the admin user
# 7. Updates clients.json

set -e

# --- Validate arguments ---
if [ $# -lt 4 ]; then
  echo ""
  echo "Usage: ./scripts/add-client.sh <business_name> <nit> <admin_email> <admin_password>"
  echo ""
  echo "Example:"
  echo "  ./scripts/add-client.sh 'Ferretería Ramírez' '900123456' 'ramirez@email.com' 'SecurePass123'"
  echo ""
  exit 1
fi

BUSINESS_NAME="$1"
NIT="$2"
ADMIN_EMAIL="$3"
ADMIN_PASSWORD="$4"

# Generate a slug from the business name (lowercase, no spaces, no special chars)
APP_SLUG=$(echo "$BUSINESS_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | cut -c1-30)
APP_NAME="rohu-${APP_SLUG}"

echo ""
echo "========================================="
echo "  ROHU Contable — Nuevo Cliente"
echo "========================================="
echo "  Negocio:  $BUSINESS_NAME"
echo "  NIT:      $NIT"
echo "  Admin:    $ADMIN_EMAIL"
echo "  App:      $APP_NAME"
echo "========================================="
echo ""

# --- Check Heroku CLI ---
if ! command -v heroku &> /dev/null; then
  echo "ERROR: Heroku CLI no está instalado. Instálalo: curl https://cli-assets.heroku.com/install.sh | sh"
  exit 1
fi

# --- 1. Create Heroku app ---
echo "[1/7] Creando app Heroku: $APP_NAME..."
heroku create "$APP_NAME" || { echo "ERROR: No se pudo crear la app. El nombre '$APP_NAME' puede estar en uso."; exit 1; }

# --- 2. Add PostgreSQL ---
echo "[2/7] Agregando PostgreSQL..."
heroku addons:create heroku-postgresql:essential-0 --app "$APP_NAME"

# --- 3. Add buildpacks ---
echo "[3/7] Configurando buildpacks..."
heroku buildpacks:add --index 1 https://github.com/heroku/heroku-buildpack-apt --app "$APP_NAME"
heroku buildpacks:add --index 2 heroku/python --app "$APP_NAME"

# --- 4. Set config vars ---
echo "[4/7] Configurando variables de entorno..."
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

heroku config:set \
  FLASK_APP="app:create_app" \
  FLASK_ENV="production" \
  DEBUG="False" \
  SECRET_KEY="$SECRET_KEY" \
  JWT_SECRET_KEY="$JWT_SECRET_KEY" \
  JWT_ACCESS_TOKEN_EXPIRES="900" \
  JWT_REFRESH_TOKEN_EXPIRES="2592000" \
  TIMEZONE="America/Bogota" \
  LOCALE="es-CO" \
  CURRENCY="COP" \
  TESSDATA_PREFIX="/app/.apt/usr/share/tesseract-ocr/5/tessdata/" \
  --app "$APP_NAME"

# --- 5. Deploy code ---
echo "[5/7] Desplegando código..."
git remote add "$APP_SLUG" "https://git.heroku.com/${APP_NAME}.git" 2>/dev/null || true
git push "$APP_SLUG" main

# --- 6. Create admin user + seed PUC ---
echo "[6/7] Creando usuario administrador y sembrando PUC..."
heroku run "python manage.py create-admin \
  --name '$BUSINESS_NAME' \
  --nit '$NIT' \
  --email '$ADMIN_EMAIL' \
  --first-name 'Admin' \
  --last-name '$BUSINESS_NAME' \
  --admin-email '$ADMIN_EMAIL' \
  --password '$ADMIN_PASSWORD'" --app "$APP_NAME"

heroku run "python manage.py seed-puc" --app "$APP_NAME"

# --- 7. Update clients.json ---
echo "[7/7] Actualizando registry de clientes..."
APP_URL=$(heroku info -s --app "$APP_NAME" | grep web_url | cut -d= -f2 | tr -d '\n')
TODAY=$(date +%Y-%m-%d)

# Add to clients.json using python (cross-platform JSON handling)
python3 -c "
import json
with open('clients.json', 'r') as f:
    clients = json.load(f)
clients.append({
    'name': '$BUSINESS_NAME',
    'app': '$APP_NAME',
    'url': '${APP_URL}',
    'admin_email': '$ADMIN_EMAIL',
    'created_at': '$TODAY'
})
with open('clients.json', 'w') as f:
    json.dump(clients, f, indent=2, ensure_ascii=False)
print(f'Added {len(clients)}th client to clients.json')
"

echo ""
echo "========================================="
echo "  CLIENTE CREADO EXITOSAMENTE"
echo "========================================="
echo "  URL:   ${APP_URL}"
echo "  Admin: $ADMIN_EMAIL"
echo "  Pass:  (la que ingresaste)"
echo ""
echo "  El cliente puede acceder a:"
echo "  ${APP_URL}app/login"
echo "========================================="
echo ""
echo "No olvides hacer commit de clients.json:"
echo "  git add clients.json && git commit -m 'feat: add client $BUSINESS_NAME' && git push origin main"
