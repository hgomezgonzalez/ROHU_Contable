"""Smoke tests — Customers + Campaigns blueprint."""


def test_list_customers(client, admin_headers):
    resp = client.get("/api/v1/customers", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_aging_report(client, admin_headers):
    resp = client.get("/api/v1/customers/aging", headers=admin_headers)
    assert resp.status_code == 200


def test_campaigns_list(client, admin_headers):
    resp = client.get("/api/v1/customers/campaigns", headers=admin_headers)
    assert resp.status_code == 200
