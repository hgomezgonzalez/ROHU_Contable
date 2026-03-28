"""Smoke tests — Invoicing blueprint."""


def test_list_invoices(client, admin_headers):
    resp = client.get("/api/v1/invoicing/", headers=admin_headers)
    assert resp.status_code == 200
