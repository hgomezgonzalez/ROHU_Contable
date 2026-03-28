"""Smoke tests — Reports blueprint."""


def test_dashboard(client, admin_headers):
    resp = client.get("/api/v1/reports/dashboard", headers=admin_headers)
    assert resp.status_code == 200


def test_stock_alerts(client, admin_headers):
    resp = client.get("/api/v1/reports/stock-alerts", headers=admin_headers)
    assert resp.status_code == 200


def test_audit_log_requires_permission(client, cashier_headers):
    """Cashiers should not have access to audit logs."""
    resp = client.get("/api/v1/reports/audit-log", headers=cashier_headers)
    assert resp.status_code == 403


def test_audit_log_admin_access(client, admin_headers):
    resp = client.get("/api/v1/reports/audit-log", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
