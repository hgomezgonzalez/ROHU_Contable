"""Integration: RBAC permission enforcement across roles."""


class TestCashierRestrictions:
    """Cashier should NOT have access to admin/accounting/audit functions."""

    def test_cannot_read_audit_logs(self, client, cashier_headers):
        resp = client.get("/api/v1/reports/audit-log", headers=cashier_headers)
        assert resp.status_code == 403

    def test_cannot_create_disbursement(self, client, cashier_headers):
        resp = client.post("/api/v1/cash/disbursements", headers=cashier_headers,
                           json={"destination_type": "expense", "concept": "test", "amount": 1000})
        assert resp.status_code == 403

    def test_cannot_approve_purchases(self, client, cashier_headers):
        resp = client.post("/api/v1/purchases/orders/fake-id/send", headers=cashier_headers)
        assert resp.status_code == 403

    def test_cannot_create_products(self, client, cashier_headers):
        resp = client.post("/api/v1/inventory/products", headers=cashier_headers,
                           json={"name": "Test", "sale_price": 100})
        assert resp.status_code == 403

    def test_can_read_products(self, client, cashier_headers):
        resp = client.get("/api/v1/inventory/products", headers=cashier_headers)
        assert resp.status_code == 200

    def test_can_read_sales(self, client, cashier_headers):
        resp = client.get("/api/v1/pos/sales", headers=cashier_headers)
        assert resp.status_code == 200


class TestViewerRestrictions:
    """Viewer should only have read access."""

    def test_cannot_create_sale(self, client, viewer_headers):
        resp = client.post("/api/v1/pos/checkout", headers=viewer_headers, json={})
        assert resp.status_code == 403

    def test_cannot_create_products(self, client, viewer_headers):
        resp = client.post("/api/v1/inventory/products", headers=viewer_headers,
                           json={"name": "Test", "sale_price": 100})
        assert resp.status_code == 403

    def test_cannot_create_customer(self, client, viewer_headers):
        resp = client.post("/api/v1/customers", headers=viewer_headers,
                           json={"name": "Test"})
        assert resp.status_code == 403

    def test_can_read_products(self, client, viewer_headers):
        resp = client.get("/api/v1/inventory/products", headers=viewer_headers)
        assert resp.status_code == 200

    def test_can_read_reports(self, client, viewer_headers):
        resp = client.get("/api/v1/reports/dashboard", headers=viewer_headers)
        assert resp.status_code == 200

    def test_can_read_cash_receipts(self, client, viewer_headers):
        resp = client.get("/api/v1/cash/receipts", headers=viewer_headers)
        assert resp.status_code == 200


class TestAdminFullAccess:
    """Admin should have access to everything."""

    def test_can_read_audit(self, client, admin_headers):
        resp = client.get("/api/v1/reports/audit-log", headers=admin_headers)
        assert resp.status_code == 200

    def test_can_manage_users(self, client, admin_headers):
        resp = client.get("/api/v1/auth/users", headers=admin_headers)
        assert resp.status_code == 200

    def test_can_read_all_reports(self, client, admin_headers):
        for endpoint in ["/api/v1/reports/dashboard", "/api/v1/reports/stock-alerts",
                         "/api/v1/reports/analytics/cash-flow"]:
            resp = client.get(endpoint, headers=admin_headers)
            assert resp.status_code == 200, f"Admin denied on {endpoint}"
