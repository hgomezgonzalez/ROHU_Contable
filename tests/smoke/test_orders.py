"""Smoke tests — Orders blueprint."""


def test_list_orders_requires_auth(client):
    resp = client.get("/api/v1/orders")
    assert resp.status_code in (401, 422)


def test_list_orders(client, admin_headers):
    resp = client.get("/api/v1/orders", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_order_stats(client, admin_headers):
    resp = client.get("/api/v1/orders/stats", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_kds_orders(client, admin_headers):
    resp = client.get("/api/v1/orders/kds", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_create_order_validation(client, admin_headers):
    resp = client.post("/api/v1/orders", json={}, headers=admin_headers)
    assert resp.status_code == 400


def test_create_order_requires_items(client, admin_headers):
    resp = client.post("/api/v1/orders", json={"items": []}, headers=admin_headers)
    assert resp.status_code == 400
