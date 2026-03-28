"""
E2E Integration flows — ROHU Contable.

Each test exercises a full business journey end-to-end through the HTTP API,
verifying that every module involved (inventory, POS, accounting, purchases,
customers, cash) responds correctly and that side-effects (stock, journal
entries) are coherent.

Fixtures used (all defined in conftest.py):
    client          — Flask test client
    admin_headers   — JWT headers for admin user
    sample_product  — A pre-created Product with stock_current=50
    tenant          — The test Tenant
    admin_user      — The admin User object
"""

import uuid


# ── Helper ────────────────────────────────────────────────────────


def _json(resp):
    """Decode response JSON and surface error messages on assertion failure."""
    data = resp.get_json()
    assert data is not None, f"Response body is not JSON: {resp.data[:400]}"
    return data


def _open_cash_session(client, admin_headers, opening_amount=50000):
    """Open a cash session and return its id. Idempotent: reuses open session."""
    resp = client.get("/api/v1/pos/cash-sessions/current", headers=admin_headers)
    if resp.status_code == 200:
        data = _json(resp)
        if data.get("success") and data.get("data"):
            return data["data"]["id"]

    resp = client.post(
        "/api/v1/pos/cash-sessions/open",
        json={"opening_amount": opening_amount},
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"open_cash_session failed: {resp.data[:300]}"
    return _json(resp)["data"]["id"]


def _create_product_via_api(client, admin_headers, tenant_id, name, sku, stock, sale_price=30000, purchase_price=15000):
    """Create a product via API and return its id."""
    resp = client.post(
        "/api/v1/inventory/products",
        json={
            "name": name,
            "sku": sku,
            "qr_code": f"QR-{uuid.uuid4().hex[:8]}",
            "sale_price": sale_price,
            "purchase_price": purchase_price,
            "tax_type": "iva_19",
            "stock_current": stock,
            "stock_minimum": 2,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"create_product failed: {resp.data[:300]}"
    return _json(resp)["data"]["id"]


def _get_product_stock(client, admin_headers, product_id):
    """Return current stock_current for a product."""
    resp = client.get("/api/v1/inventory/stock", headers=admin_headers)
    assert resp.status_code == 200
    items = _json(resp).get("data", [])
    for item in items:
        if item["product_id"] == product_id:
            return item["stock_current"]
    # Fallback: query product list
    resp2 = client.get("/api/v1/inventory/products", headers=admin_headers)
    products = _json(resp2).get("data", [])
    for p in products:
        if p["id"] == product_id:
            return p.get("stock_current", None)
    return None


def _count_journal_entries(client, admin_headers):
    """Return total journal entries count."""
    resp = client.get("/api/v1/accounting/journal", headers=admin_headers)
    assert resp.status_code == 200
    data = _json(resp)
    return data.get("total", len(data.get("data", [])))


def _get_journal_entries(client, admin_headers):
    """Return list of journal entries."""
    resp = client.get("/api/v1/accounting/journal?per_page=100", headers=admin_headers)
    assert resp.status_code == 200
    return _json(resp).get("data", [])


def _seed_accounts_if_needed(client, admin_headers):
    """Seed PUC accounts if the tenant has none yet."""
    resp = client.get("/api/v1/accounting/accounts", headers=admin_headers)
    data = _json(resp)
    if not data.get("data"):
        seed_resp = client.post("/api/v1/accounting/accounts/seed", headers=admin_headers)
        assert seed_resp.status_code == 200, f"seed_accounts failed: {seed_resp.data[:300]}"


# ── Flow 1: Product → Cash Session → Checkout → Stock → Journal ──


class TestPOSCheckoutE2EFlow:
    """
    E2E-FLOW-001: Full POS sale journey.

    Given a product with stock
    When a cashier opens a cash session and completes a checkout
    Then stock must decrease by the sold quantity
    And a journal entry must be created automatically
    """

    def test_checkout_decrements_stock_and_posts_journal_entry(
        self, client, admin_headers, sample_product, tenant
    ):
        # Seed PUC accounts (required for auto-posting)
        _seed_accounts_if_needed(client, admin_headers)

        product_id = str(sample_product.id)
        initial_stock = float(sample_product.stock_current)  # 50

        # Step 1: Get baseline journal entry count
        entries_before = _count_journal_entries(client, admin_headers)

        # Step 2: Open cash session
        session_id = _open_cash_session(client, admin_headers, opening_amount=100000)

        # Step 3: Execute checkout — sell 3 units
        qty_sold = 3
        resp = client.post(
            "/api/v1/pos/checkout",
            json={
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": qty_sold,
                        "discount_pct": 0,
                    }
                ],
                "payments": [
                    {
                        "method": "cash",
                        "amount": float(sample_product.sale_price) * qty_sold * 1.19,
                        "received_amount": float(sample_product.sale_price) * qty_sold * 1.19,
                    }
                ],
                "cash_session_id": session_id,
                "customer_name": "Cliente Mostrador",
                "sale_type": "cash",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201, f"checkout failed: {resp.data[:400]}"
        sale_data = _json(resp)["data"]
        assert sale_data["status"] == "completed"
        sale_id = sale_data["id"]

        # Step 4: Verify stock decreased
        new_stock = _get_product_stock(client, admin_headers, product_id)
        assert new_stock is not None, "Could not retrieve updated stock"
        expected_stock = initial_stock - qty_sold
        assert float(new_stock) == expected_stock, (
            f"Expected stock {expected_stock}, got {new_stock}"
        )

        # Step 5: Verify journal entries were created (at least 1 more)
        entries_after = _count_journal_entries(client, admin_headers)
        assert entries_after > entries_before, (
            f"Expected new journal entries after sale, still have {entries_after}"
        )

        # Step 6: Verify sale is retrievable
        resp2 = client.get(f"/api/v1/pos/sales/{sale_id}", headers=admin_headers)
        assert resp2.status_code == 200
        assert _json(resp2)["data"]["id"] == sale_id


# ── Flow 2: Supplier → PO → Send → Receive → Stock Increase ──────


class TestPurchaseOrderE2EFlow:
    """
    E2E-FLOW-002: Full purchase order journey.

    Given a supplier and a product
    When a PO is created, sent, and received
    Then product stock must increase by the received quantity
    """

    def test_create_send_receive_po_increments_stock(
        self, client, admin_headers, sample_product, tenant
    ):
        _seed_accounts_if_needed(client, admin_headers)

        product_id = str(sample_product.id)
        initial_stock = float(sample_product.stock_current)

        # Step 1: Create supplier
        supplier_resp = client.post(
            "/api/v1/purchases/suppliers",
            json={
                "name": f"Proveedor E2E {uuid.uuid4().hex[:6]}",
                "tax_id": f"900{uuid.uuid4().hex[:6]}",
                "city": "Medellín",
                "payment_terms_days": 30,
            },
            headers=admin_headers,
        )
        assert supplier_resp.status_code == 201, f"create_supplier failed: {supplier_resp.data[:300]}"
        supplier_id = _json(supplier_resp)["data"]["id"]

        # Step 2: Create purchase order
        qty_ordered = 10
        po_resp = client.post(
            "/api/v1/purchases/orders",
            json={
                "supplier_id": supplier_id,
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": qty_ordered,        # service reads item_data["quantity"]
                        "unit_cost": float(sample_product.purchase_price),
                        "tax_rate": 19.0,
                    }
                ],
                "payment_type": "credit",
            },
            headers=admin_headers,
        )
        assert po_resp.status_code == 201, f"create_po failed: {po_resp.data[:300]}"
        po_id = _json(po_resp)["data"]["id"]
        assert _json(po_resp)["data"]["status"] == "draft"

        # Step 3: Send the PO
        send_resp = client.post(
            f"/api/v1/purchases/orders/{po_id}/send",
            headers=admin_headers,
        )
        assert send_resp.status_code == 200, f"send_po failed: {send_resp.data[:300]}"
        assert _json(send_resp)["data"]["status"] == "sent"

        # Step 4: Receive the PO (full reception)
        receive_resp = client.post(
            f"/api/v1/purchases/orders/{po_id}/receive",
            json={},  # Full reception uses ordered quantities
            headers=admin_headers,
        )
        assert receive_resp.status_code == 200, f"receive_po failed: {receive_resp.data[:300]}"
        po_received = _json(receive_resp)["data"]
        assert po_received["status"] == "received"

        # Step 5: Verify stock increased
        new_stock = _get_product_stock(client, admin_headers, product_id)
        assert new_stock is not None
        expected_stock = initial_stock + qty_ordered
        assert float(new_stock) == expected_stock, (
            f"Expected stock {expected_stock} after receiving PO, got {new_stock}"
        )


# ── Flow 3: Customer → Credit Sale → Payment → Amount Due ────────


class TestCreditSaleAndPaymentE2EFlow:
    """
    E2E-FLOW-003: Credit sale and customer payment journey.

    Given a customer
    When a credit sale is made
    Then payment_status must be 'pending' and amount_due == total_amount
    When a partial payment is registered
    Then amount_due must decrease
    """

    def test_credit_sale_then_payment_reduces_amount_due(
        self, client, admin_headers, sample_product, tenant
    ):
        _seed_accounts_if_needed(client, admin_headers)

        product_id = str(sample_product.id)
        sale_price = float(sample_product.sale_price)  # 25000

        # Step 1: Create customer
        customer_resp = client.post(
            "/api/v1/customers",
            json={
                "name": f"Cliente Crédito {uuid.uuid4().hex[:6]}",
                "tax_id": f"CC{uuid.uuid4().hex[:6]}",
                "tax_id_type": "CC",
                "city": "Bogotá",
                "credit_limit": 500000,
                "credit_days": 30,
            },
            headers=admin_headers,
        )
        assert customer_resp.status_code == 201, f"create_customer failed: {customer_resp.data[:300]}"
        customer_id = _json(customer_resp)["data"]["id"]

        # Step 2: Make a credit sale (no payments required for credit)
        qty = 2
        credit_resp = client.post(
            "/api/v1/pos/checkout",
            json={
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": qty,
                        "discount_pct": 0,
                    }
                ],
                "payments": [],
                "sale_type": "credit",
                "customer_id": customer_id,
                "credit_days": 30,
            },
            headers=admin_headers,
        )
        assert credit_resp.status_code == 201, f"credit_sale failed: {credit_resp.data[:400]}"
        sale = _json(credit_resp)["data"]
        sale_id = sale["id"]

        assert sale["sale_type"] == "credit"
        assert sale["payment_status"] == "pending"
        total_amount = float(sale["total_amount"])
        amount_due_before = float(sale["amount_due"])
        assert amount_due_before == total_amount, (
            f"amount_due {amount_due_before} should equal total {total_amount} on new credit sale"
        )

        # Step 3: Register a partial payment (abono)
        payment_amount = total_amount / 2  # 50% payment
        payment_resp = client.post(
            f"/api/v1/customers/{customer_id}/payments",
            json={
                "amount": payment_amount,
                "payment_method": "cash",
                "sale_id": sale_id,
                "notes": "Abono parcial E2E test",
            },
            headers=admin_headers,
        )
        assert payment_resp.status_code == 201, f"customer_payment failed: {payment_resp.data[:300]}"

        # Step 4: Verify amount_due decreased via sale detail
        sale_resp = client.get(f"/api/v1/pos/sales/{sale_id}", headers=admin_headers)
        assert sale_resp.status_code == 200
        updated_sale = _json(sale_resp)["data"]
        amount_due_after = float(updated_sale["amount_due"])

        assert amount_due_after < amount_due_before, (
            f"amount_due should decrease after payment. Before: {amount_due_before}, After: {amount_due_after}"
        )
        # Tolerance of 1 peso for rounding
        assert abs(amount_due_after - (amount_due_before - payment_amount)) <= 1, (
            f"Expected amount_due ~{amount_due_before - payment_amount}, got {amount_due_after}"
        )


# ── Flow 4: Cash Receipt → Journal Entry → Void → Reversal ───────


class TestCashReceiptVoidE2EFlow:
    """
    E2E-FLOW-004: Cash receipt generates journal entry; voiding creates reversal.

    Given the PUC accounts are seeded
    When a cash receipt is created
    Then a journal entry must appear
    When the receipt is voided
    Then a reversal journal entry must appear (total entries += 1 more)
    """

    def test_cash_receipt_creates_journal_entry_and_void_creates_reversal(
        self, client, admin_headers
    ):
        _seed_accounts_if_needed(client, admin_headers)

        entries_before = _count_journal_entries(client, admin_headers)

        # Step 1: Create cash receipt
        receipt_resp = client.post(
            "/api/v1/cash/receipts",
            json={
                "source_type": "other_income",
                "concept": "Ingreso misceláneo E2E test",
                "amount": 75000,
                "payment_method": "cash",
                "reference": f"REF-{uuid.uuid4().hex[:8]}",
            },
            headers=admin_headers,
        )
        assert receipt_resp.status_code == 201, f"create_receipt failed: {receipt_resp.data[:300]}"
        receipt = _json(receipt_resp)["data"]
        receipt_id = receipt["id"]
        assert receipt["status"] == "active"

        # Step 2: Verify at least one new journal entry was generated
        entries_after_create = _count_journal_entries(client, admin_headers)
        assert entries_after_create > entries_before, (
            "No journal entry was created after cash receipt"
        )

        # Step 3: Void the receipt
        void_resp = client.post(
            f"/api/v1/cash/receipts/{receipt_id}/void",
            headers=admin_headers,
        )
        assert void_resp.status_code == 200, f"void_receipt failed: {void_resp.data[:300]}"
        voided_receipt = _json(void_resp)["data"]
        assert voided_receipt["status"] == "voided"

        # Step 4: Verify reversal journal entry was created
        entries_after_void = _count_journal_entries(client, admin_headers)
        assert entries_after_void > entries_after_create, (
            "No reversal journal entry was created after voiding the receipt"
        )


# ── Flow 5: Expense (caused) → Journal → Pay → Status Paid ───────


class TestExpensePaymentE2EFlow:
    """
    E2E-FLOW-005: Create a caused expense, verify journal entry,
    then pay it and verify payment_status changes to 'paid'.

    Given the PUC accounts are seeded
    When a 'pending' expense is created
    Then a journal entry for the accrual must exist
    When the expense is paid
    Then its payment_status becomes 'paid' and another journal entry appears
    """

    def test_create_caused_expense_then_pay_posts_entries(
        self, client, admin_headers
    ):
        _seed_accounts_if_needed(client, admin_headers)

        entries_before = _count_journal_entries(client, admin_headers)

        # Step 1: Create a caused (pending) expense
        expense_resp = client.post(
            "/api/v1/accounting/expenses",
            json={
                "puc_code": "5195",          # Gastos diversos
                "concept": "Servicios públicos E2E test",
                "amount": 120000,
                "tax_amount": 0,
                "payment_status": "pending",  # Caused / accrued
                "payment_method": "cash",
            },
            headers=admin_headers,
        )
        assert expense_resp.status_code == 201, f"create_expense failed: {expense_resp.data[:400]}"
        expense = _json(expense_resp)["data"]
        expense_id = expense["id"]
        assert expense["payment_status"] == "pending"

        # Step 2: Verify journal entry was created for accrual
        entries_after_create = _count_journal_entries(client, admin_headers)
        assert entries_after_create > entries_before, (
            "No journal entry created for caused expense"
        )

        # Step 3: Pay the expense
        pay_resp = client.post(
            f"/api/v1/accounting/expenses/{expense_id}/pay",
            json={"payment_method": "cash"},
            headers=admin_headers,
        )
        assert pay_resp.status_code == 200, f"pay_expense failed: {pay_resp.data[:300]}"
        paid_expense = _json(pay_resp)["data"]
        assert paid_expense["payment_status"] == "paid", (
            f"Expected payment_status='paid' after payment, got '{paid_expense['payment_status']}'"
        )

        # Step 4: Verify another journal entry was created for the payment
        entries_after_pay = _count_journal_entries(client, admin_headers)
        assert entries_after_pay > entries_after_create, (
            "No journal entry created for expense payment settlement"
        )
