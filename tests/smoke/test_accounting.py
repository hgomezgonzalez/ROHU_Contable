"""Smoke tests — Accounting blueprint."""


def test_list_accounts_requires_auth(client):
    resp = client.get("/api/v1/accounting/accounts")
    assert resp.status_code in (401, 422)


def test_list_accounts(client, admin_headers):
    resp = client.get("/api/v1/accounting/accounts", headers=admin_headers)
    assert resp.status_code == 200


def test_journal(client, admin_headers):
    resp = client.get("/api/v1/accounting/journal", headers=admin_headers)
    assert resp.status_code == 200
