"""Smoke tests — Vouchers blueprint."""


def test_list_types_requires_auth(client):
    resp = client.get("/api/v1/vouchers/types")
    assert resp.status_code in (401, 422)


def test_list_types(client, admin_headers):
    resp = client.get("/api/v1/vouchers/types", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_list_vouchers(client, admin_headers):
    resp = client.get("/api/v1/vouchers/", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_voucher_stats(client, admin_headers):
    resp = client.get("/api/v1/vouchers/stats", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "by_status" in data["data"]


def test_validate_requires_code(client, admin_headers):
    resp = client.post("/api/v1/vouchers/validate", json={}, headers=admin_headers)
    assert resp.status_code == 400


def test_redeem_requires_auth(client):
    resp = client.post("/api/v1/vouchers/redeem", json={"code": "TEST"})
    assert resp.status_code in (401, 422)


def test_create_type_validation(client, admin_headers):
    # Missing required fields
    resp = client.post("/api/v1/vouchers/types", json={}, headers=admin_headers)
    assert resp.status_code == 400

    # Validity too short (min 90 days)
    resp = client.post(
        "/api/v1/vouchers/types", json={"name": "Test", "face_value": 10000, "validity_days": 30}, headers=admin_headers
    )
    assert resp.status_code == 400


def test_emit_validation(client, admin_headers):
    # Non-existent type
    resp = client.post(
        "/api/v1/vouchers/emit", json={"type_id": "00000000-0000-0000-0000-000000000000"}, headers=admin_headers
    )
    assert resp.status_code in (400, 404)
