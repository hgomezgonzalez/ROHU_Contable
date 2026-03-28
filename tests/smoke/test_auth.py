"""Smoke tests — Auth RBAC blueprint."""


def test_login_requires_credentials(client):
    resp = client.post("/api/v1/auth/login", json={})
    assert resp.status_code in (400, 401)


def test_me_requires_auth(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 422)


def test_me_with_valid_token(client, admin_headers):
    resp = client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_get_tenant(client, admin_headers):
    resp = client.get("/api/v1/auth/tenant", headers=admin_headers)
    assert resp.status_code == 200


def test_list_users(client, admin_headers):
    resp = client.get("/api/v1/auth/users", headers=admin_headers)
    assert resp.status_code == 200
