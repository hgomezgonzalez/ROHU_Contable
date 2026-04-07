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

# Timeouts (seconds)
BUILD_TIMEOUT = 600  # 10 min
RELEASE_TIMEOUT = 600  # 10 min
HEALTH_TIMEOUT = 60  # 1 min
MAX_TOTAL_TIMEOUT = 900  # 15 min absolute max


def _read_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        # Auto-expire stuck deploys (> 15 min)
        if state.get("running") and state.get("started_at"):
            started = datetime.fromisoformat(state["started_at"])
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            if elapsed > MAX_TOTAL_TIMEOUT:
                state["running"] = False
                state["finished_at"] = datetime.now(timezone.utc).isoformat()
                for app_data in state.get("apps", {}).values():
                    if app_data.get("status") not in ("healthy", "failed"):
                        app_data["status"] = "failed"
                        app_data["detail"] = "Timeout - el despliegue tomo mas de 15 minutos"
                _write_state(state)
        return state
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {"running": False, "apps": {}, "started_at": None, "finished_at": None}


def _write_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, default=str)


def _heroku_headers(api_key: str) -> dict:
    return {**HEROKU_HEADERS, "Authorization": f"Bearer {api_key}"}


def _read_clients() -> list:
    """Read clients.json excluding the current app."""
    clients_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "clients.json"
    )
    with open(clients_file, "r") as f:
        all_clients = json.load(f)
    current_app = os.getenv("HEROKU_APP_NAME", "rohu-contable-prod")
    return [c for c in all_clients if c.get("app") != current_app]


def get_deploy_status() -> dict:
    return _read_state()


def start_deploy_all() -> dict:
    state = _read_state()
    if state.get("running"):
        raise ValueError("Ya hay un despliegue en curso. Espere a que termine.")

    from flask import current_app

    api_key = current_app.config.get("HEROKU_API_KEY") or os.getenv("ROHU_HEROKU_KEY", "")
    github_repo = current_app.config.get("GITHUB_REPO") or os.getenv("GITHUB_REPO", "hgomezgonzalez/ROHU_Contable")

    if not api_key:
        raise ValueError("ROHU_HEROKU_KEY no configurada. Agreguela en Heroku Config Vars.")

    clients = _read_clients()
    if not clients:
        raise ValueError("No hay replicas para sincronizar en clients.json")

    source_url = f"https://github.com/{github_repo}/archive/refs/heads/main.tar.gz"

    state = {
        "running": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "total": len(clients),
        "completed": 0,
        "failed": 0,
        "apps": {c["app"]: {"name": c["name"], "status": "pending", "detail": "En espera..."} for c in clients},
    }
    _write_state(state)

    t = threading.Thread(target=_deploy_worker, args=(clients, api_key, source_url), daemon=True)
    t.start()

    return state


def _deploy_worker(clients: list, api_key: str, source_url: str):
    headers = _heroku_headers(api_key)
    state = _read_state()
    start_time = time.time()

    for client in clients:
        app_name = client["app"]

        # Check absolute timeout
        if time.time() - start_time > MAX_TOTAL_TIMEOUT:
            state["apps"][app_name] = {
                "name": client.get("name", app_name),
                "status": "failed",
                "detail": "Timeout global alcanzado",
            }
            state["failed"] += 1
            _write_state(state)
            continue

        try:
            _deploy_single_app(app_name, headers, source_url, state)
            state["completed"] += 1
        except Exception as e:
            logger.error("Deploy failed for %s: %s", app_name, str(e), exc_info=True)
            state["apps"][app_name] = {
                "name": client.get("name", app_name),
                "status": "failed",
                "detail": str(e)[:200],
            }
            state["failed"] += 1
            _write_state(state)

    state["running"] = False
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_state(state)
    logger.info("Deploy finished: %d ok, %d failed", state["completed"], state["failed"])


def _deploy_single_app(app_name: str, headers: dict, source_url: str, state: dict):
    # Step 1: Config
    _update_status(state, app_name, "building", "Verificando configuracion...")
    _ensure_voucher_secret(app_name, headers)

    # Step 2: Create build
    _update_status(state, app_name, "building", "Iniciando build...")
    build_id = _create_build(app_name, headers, source_url)

    # Step 3: Wait for build
    _update_status(state, app_name, "building", "Compilando aplicacion...")
    _wait_for_build(app_name, headers, build_id, state)

    # Step 4: Wait for release
    _update_status(state, app_name, "releasing", "Ejecutando migraciones...")
    _wait_for_release(app_name, headers, state)

    # Step 5: Health check (wait for dyno restart)
    _update_status(state, app_name, "releasing", "Esperando reinicio de la app...")
    time.sleep(15)  # Heroku needs time to restart dynos after release
    _update_status(state, app_name, "releasing", "Verificando app...")
    _health_check(app_name)

    _update_status(state, app_name, "healthy", "Sincronizado correctamente")


def _update_status(state: dict, app_name: str, status: str, detail: str):
    if app_name in state["apps"]:
        state["apps"][app_name]["status"] = status
        state["apps"][app_name]["detail"] = detail
    _write_state(state)


def _ensure_voucher_secret(app_name: str, headers: dict):
    try:
        resp = requests.get(f"{HEROKU_API}/apps/{app_name}/config-vars", headers=headers, timeout=15)
        if resp.status_code == 200 and not resp.json().get("VOUCHER_HMAC_SECRET"):
            import secrets

            requests.patch(
                f"{HEROKU_API}/apps/{app_name}/config-vars",
                headers=headers,
                json={"VOUCHER_HMAC_SECRET": secrets.token_hex(32)},
                timeout=15,
            )
    except Exception as e:
        logger.warning("Could not check VOUCHER_HMAC_SECRET for %s: %s", app_name, e)


def _create_build(app_name: str, headers: dict, source_url: str) -> str:
    resp = requests.post(
        f"{HEROKU_API}/apps/{app_name}/builds",
        headers=headers,
        json={"source_blob": {"url": source_url, "version": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Build API error {resp.status_code}: {resp.text[:150]}")
    return resp.json()["id"]


def _wait_for_build(app_name: str, headers: dict, build_id: str, state: dict):
    deadline = time.time() + BUILD_TIMEOUT
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            resp = requests.get(f"{HEROKU_API}/apps/{app_name}/builds/{build_id}", headers=headers, timeout=15)
            if resp.status_code == 200:
                status = resp.json().get("status", "pending")
                if status == "succeeded":
                    return
                if status == "failed":
                    raise RuntimeError("Build fallido — revise los logs en Heroku Dashboard")
                _update_status(state, app_name, "building", f"Compilando... ({attempt * 10}s)")
        except requests.RequestException:
            pass
        time.sleep(10)
    raise RuntimeError("Build timeout (10 min)")


def _wait_for_release(app_name: str, headers: dict, state: dict):
    time.sleep(10)  # Give Heroku time to start release
    deadline = time.time() + RELEASE_TIMEOUT
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            resp = requests.get(
                f"{HEROKU_API}/apps/{app_name}/releases",
                headers={**headers, "Range": "version ..; order=desc,max=1"},
                timeout=15,
            )
            if resp.status_code in (200, 206):
                releases = resp.json()
                if releases:
                    status = releases[0].get("status", "pending")
                    if status == "succeeded":
                        return
                    if status == "failed":
                        raise RuntimeError("Release fallido — migraciones o seeds con error")
                    _update_status(state, app_name, "releasing", f"Migraciones... ({attempt * 10}s)")
        except requests.RequestException:
            pass
        time.sleep(10)
    raise RuntimeError("Release timeout (10 min)")


def _health_check(app_name: str):
    url = f"https://{app_name}.herokuapp.com/health"
    deadline = time.time() + 120  # 2 minutes for health check
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(10)
    raise RuntimeError(f"Health check fallido despues de {attempt} intentos (2 min)")
