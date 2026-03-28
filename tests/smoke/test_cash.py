"""Smoke tests — Cash module (receipts, disbursements, transfers)."""


def test_list_receipts(client, admin_headers):
    resp = client.get("/api/v1/cash/receipts", headers=admin_headers)
    assert resp.status_code == 200


def test_list_disbursements(client, admin_headers):
    resp = client.get("/api/v1/cash/disbursements", headers=admin_headers)
    assert resp.status_code == 200


def test_list_transfers(client, admin_headers):
    resp = client.get("/api/v1/cash/transfers", headers=admin_headers)
    assert resp.status_code == 200


def test_cashier_cannot_create_disbursement(client, cashier_headers):
    resp = client.post("/api/v1/cash/disbursements", headers=cashier_headers,
                       json={"destination_type": "expense", "concept": "test", "amount": 1000})
    assert resp.status_code == 403
