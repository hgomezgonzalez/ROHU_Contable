"""Integration: verify ALL list endpoints respond 200 with admin token."""

import pytest

ENDPOINTS = [
    "/api/v1/auth/me",
    "/api/v1/auth/tenant",
    "/api/v1/auth/users",
    "/api/v1/inventory/products",
    "/api/v1/inventory/categories",
    "/api/v1/inventory/stock",
    "/api/v1/inventory/movements",
    "/api/v1/pos/sales",
    "/api/v1/pos/daily-totals",
    "/api/v1/accounting/accounts",
    "/api/v1/accounting/journal",
    "/api/v1/accounting/expenses",
    "/api/v1/purchases/suppliers",
    "/api/v1/purchases/orders",
    "/api/v1/purchases/credit-notes",
    "/api/v1/invoicing/",
    "/api/v1/reports/dashboard",
    "/api/v1/reports/stock-alerts",
    "/api/v1/reports/audit-log",
    "/api/v1/reports/analytics/margins",
    "/api/v1/reports/analytics/cash-flow",
    "/api/v1/reports/analytics/receivables-payables",
    "/api/v1/reports/analytics/expenses-trend",
    "/api/v1/reports/analytics/inventory-rotation",
    "/api/v1/customers",
    "/api/v1/customers/aging",
    "/api/v1/customers/campaigns",
    "/api/v1/cash/receipts",
    "/api/v1/cash/disbursements",
    "/api/v1/cash/transfers",
]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_endpoint_responds_200(client, admin_headers, endpoint):
    resp = client.get(endpoint, headers=admin_headers)
    assert resp.status_code == 200, f"{endpoint} returned {resp.status_code}: {resp.data[:200]}"
