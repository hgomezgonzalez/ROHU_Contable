"""Smoke tests — Analytics endpoints."""


def test_product_margins(client, admin_headers):
    resp = client.get("/api/v1/reports/analytics/margins", headers=admin_headers)
    assert resp.status_code == 200


def test_cash_flow(client, admin_headers):
    resp = client.get("/api/v1/reports/analytics/cash-flow", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_receivables_payables(client, admin_headers):
    resp = client.get("/api/v1/reports/analytics/receivables-payables", headers=admin_headers)
    assert resp.status_code == 200


def test_expenses_trend(client, admin_headers):
    resp = client.get("/api/v1/reports/analytics/expenses-trend", headers=admin_headers)
    assert resp.status_code == 200


def test_inventory_rotation(client, admin_headers):
    resp = client.get("/api/v1/reports/analytics/inventory-rotation", headers=admin_headers)
    assert resp.status_code == 200


def test_viewer_can_read_analytics(client, viewer_headers):
    """Viewers should have reports:read permission."""
    resp = client.get("/api/v1/reports/analytics/cash-flow", headers=viewer_headers)
    assert resp.status_code == 200
