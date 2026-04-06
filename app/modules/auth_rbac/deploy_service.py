"""Deploy service — Sync code to all SaaS client replicas via Heroku Build API."""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

STATE_FILE = "/tmp/rohu_deploy_state.json"
HEROKU_API = "https://api.heroku.com"
HEROKU_HEADERS = {
    "Accept": "application/vnd.heroku+json; version=3",
    "Content-Type": "application/json",
}


def _read_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"running": False, "apps": {}, "started_at": None, "finished_at": None}


def _write_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, default=str)


def _heroku_headers(api_key: str) -> dict:
    return {**HEROKU_HEADERS, "Authorization": f"Bearer {api_key}"}


def _read_clients() -> list:
    # __file__ = app/modules/auth_rbac/deploy_service.py → need 4 levels up to reach project root
    clients_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "clients.json")
    with open(clients_file, "r") as f:
        return json.load(f)


def get_deploy_status() -> dict:
    """Return current deploy state (for polling)."""
    return _read_state()


def start_deploy_all() -> dict:
    """Start deploying to all client apps. Returns initial state."""
    state = _read_state()
    if state.get("running"):
        raise ValueError("Ya hay un despliegue en curso. Espere a que termine.")

    from flask import current_app

    api_key = current_app.config.get("HEROKU_API_KEY") or os.getenv("ROHU_HEROKU_KEY", "")
    github_repo = current_app.config.get("GITHUB_REPO") or os.getenv("GITHUB_REPO", "hgomezgonzalez/ROHU_Contable")

    if not api_key:
        raise ValueError("HEROKU_API_KEY no está configurada. Agréguela en las variables de entorno de Heroku.")

    clients = _read_clients()
    if not clients:
        raise ValueError("No hay clientes registrados en clients.json")

    source_url = f"https://github.com/{github_repo}/archive/refs/heads/main.tar.gz"

    # Initialize state
    state = {
        "running": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "source_url": source_url,
        "total": len(clients),
        "completed": 0,
        "failed": 0,
        "apps": {c["app"]: {"name": c["name"], "status": "pending", "detail": "En espera..."} for c in clients},
    }
    _write_state(state)

    # Start background thread
    t = threading.Thread(
        target=_deploy_worker,
        args=(clients, api_key, source_url),
        daemon=True,
    )
    t.start()

    return state


def _deploy_worker(clients: list, api_key: str, source_url: str):
    """Background worker: deploy to each app sequentially."""
    headers = _heroku_headers(api_key)
    state = _read_state()

    for client in clients:
        app_name = client["app"]
        try:
            _deploy_single_app(app_name, headers, source_url, state)
            state["completed"] += 1
        except Exception as e:
            logger.error("Deploy failed for %s: %s", app_name, str(e), exc_info=True)
            state["apps"][app_name] = {"name": client.get("name", app_name), "status": "failed", "detail": str(e)[:200]}
            state["failed"] += 1
            _write_state(state)

    state["running"] = False
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_state(state)
    logger.info("Deploy all finished: %d completed, %d failed", state["completed"], state["failed"])


def _deploy_single_app(app_name: str, headers: dict, source_url: str, state: dict):
    """Deploy to a single Heroku app: build → release → health check."""

    # Step 1: Ensure VOUCHER_HMAC_SECRET
    _update_app_status(state, app_name, "building", "Verificando configuracion...")
    _ensure_voucher_secret(app_name, headers)

    # Step 2: Create build
    _update_app_status(state, app_name, "building", "Creando build...")
    build_id = _create_build(app_name, headers, source_url)

    # Step 3: Wait for build to complete
    _update_app_status(state, app_name, "building", "Construyendo aplicacion...")
    _wait_for_build(app_name, headers, build_id, state)

    # Step 4: Wait for release phase (migrations + seed)
    _update_app_status(state, app_name, "releasing", "Ejecutando migraciones y seeds...")
    _wait_for_release(app_name, headers, state)

    # Step 5: Health check
    _update_app_status(state, app_name, "releasing", "Verificando salud de la app...")
    _health_check(app_name, state)

    _update_app_status(state, app_name, "healthy", "Desplegado correctamente")


def _update_app_status(state: dict, app_name: str, status: str, detail: str):
    if app_name in state["apps"]:
        state["apps"][app_name]["status"] = status
        state["apps"][app_name]["detail"] = detail
    _write_state(state)


def _ensure_voucher_secret(app_name: str, headers: dict):
    """Ensure VOUCHER_HMAC_SECRET is set on the app."""
    resp = requests.get(f"{HEROKU_API}/apps/{app_name}/config-vars", headers=headers, timeout=15)
    if resp.status_code == 200:
        config = resp.json()
        if not config.get("VOUCHER_HMAC_SECRET"):
            import secrets

            secret = secrets.token_hex(32)
            requests.patch(
                f"{HEROKU_API}/apps/{app_name}/config-vars",
                headers=headers,
                json={"VOUCHER_HMAC_SECRET": secret},
                timeout=15,
            )
            logger.info("Set VOUCHER_HMAC_SECRET for %s", app_name)


def _create_build(app_name: str, headers: dict, source_url: str) -> str:
    """Create a Heroku build from GitHub tarball. Returns build ID."""
    resp = requests.post(
        f"{HEROKU_API}/apps/{app_name}/builds",
        headers=headers,
        json={"source_blob": {"url": source_url, "version": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Error creando build: {resp.status_code} — {resp.text[:200]}")

    build = resp.json()
    return build["id"]


def _wait_for_build(app_name: str, headers: dict, build_id: str, state: dict):
    """Poll build status until succeeded or failed. Max ~5 minutes."""
    for attempt in range(30):
        resp = requests.get(f"{HEROKU_API}/apps/{app_name}/builds/{build_id}", headers=headers, timeout=15)
        if resp.status_code != 200:
            time.sleep(10)
            continue

        build = resp.json()
        status = build.get("status", "pending")

        if status == "succeeded":
            return
        elif status == "failed":
            raise RuntimeError(f"Build fallido para {app_name}")

        _update_app_status(state, app_name, "building", f"Construyendo... (intento {attempt + 1})")
        time.sleep(10)

    raise RuntimeError(f"Build timeout para {app_name} (5 min)")


def _wait_for_release(app_name: str, headers: dict, state: dict):
    """Wait for release phase (migrations + seed) to complete. Max ~3 minutes."""
    time.sleep(5)  # Give Heroku a moment to start the release

    for attempt in range(18):
        resp = requests.get(
            f"{HEROKU_API}/apps/{app_name}/releases",
            headers={**headers, "Range": "version ..; order=desc,max=1"},
            timeout=15,
        )
        if resp.status_code != 200:
            time.sleep(10)
            continue

        releases = resp.json()
        if not releases:
            time.sleep(10)
            continue

        status = releases[0].get("status", "pending")
        if status == "succeeded":
            return
        elif status == "failed":
            raise RuntimeError(f"Release fallido para {app_name} (migraciones o seeds)")

        _update_app_status(state, app_name, "releasing", f"Migraciones en curso... (intento {attempt + 1})")
        time.sleep(10)

    raise RuntimeError(f"Release timeout para {app_name} (3 min)")


def _health_check(app_name: str, state: dict):
    """Verify the app is healthy after deploy."""
    url = f"https://{app_name}.herokuapp.com/health"

    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                return
        except requests.RequestException:
            pass
        _update_app_status(state, app_name, "releasing", f"Health check intento {attempt + 1}/3...")
        time.sleep(10)

    raise RuntimeError(f"Health check fallido para {app_name}")
