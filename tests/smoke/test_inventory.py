"""Smoke tests — Inventory blueprint."""


def test_list_products_requires_auth(client):
    resp = client.get("/api/v1/inventory/products")
    assert resp.status_code in (401, 422)


def test_list_products(client, admin_headers):
    resp = client.get("/api/v1/inventory/products", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_list_categories(client, admin_headers):
    resp = client.get("/api/v1/inventory/categories", headers=admin_headers)
    assert resp.status_code == 200


def test_stock_levels(client, admin_headers):
    resp = client.get("/api/v1/inventory/stock", headers=admin_headers)
    assert resp.status_code == 200


def test_movements(client, admin_headers):
    resp = client.get("/api/v1/inventory/movements", headers=admin_headers)
    assert resp.status_code == 200
