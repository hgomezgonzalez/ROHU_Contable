"""Smoke tests — Purchases blueprint."""


def test_list_suppliers(client, admin_headers):
    resp = client.get("/api/v1/purchases/suppliers", headers=admin_headers)
    assert resp.status_code == 200


def test_list_orders(client, admin_headers):
    resp = client.get("/api/v1/purchases/orders", headers=admin_headers)
    assert resp.status_code == 200
