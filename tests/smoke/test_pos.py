"""Smoke tests — POS blueprint."""


def test_current_session_requires_auth(client):
    resp = client.get("/api/v1/pos/cash-sessions/current")
    assert resp.status_code in (401, 422)


def test_current_session(client, admin_headers):
    resp = client.get("/api/v1/pos/cash-sessions/current", headers=admin_headers)
    # May return 200 (no session) or 404 depending on implementation
    assert resp.status_code in (200, 404)


def test_list_sales(client, admin_headers):
    resp = client.get("/api/v1/pos/sales", headers=admin_headers)
    assert resp.status_code == 200


def test_daily_totals(client, admin_headers):
    resp = client.get("/api/v1/pos/daily-totals", headers=admin_headers)
    assert resp.status_code == 200
