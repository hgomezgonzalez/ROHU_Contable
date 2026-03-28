"""Electronic invoicing services — DIAN via PTA integration."""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.modules.auth_rbac.models import Tenant
from app.modules.invoicing.models import ElectronicInvoice
from app.modules.pos.models import Sale, CreditNote


def _next_einvoice_number(tenant_id: str) -> tuple:
    """Generate next sequential e-invoice number with tenant prefix."""
    tenant = Tenant.query.get(tenant_id)
    prefix = getattr(tenant, 'dian_resolution_prefix', '') or 'FE'

    last = (
        db.session.query(func.max(ElectronicInvoice.invoice_number))
        .filter(
            ElectronicInvoice.tenant_id == tenant_id,
            ElectronicInvoice.invoice_number.like(f"{prefix}%"),
        )
        .scalar()
    )

    if last:
        seq = int(last.replace(prefix, '')) + 1
    else:
        seq = 1

    return prefix, f"{prefix}{seq:06d}"


def generate_invoice(
    tenant_id: str, sale_id: str, created_by: str,
    customer_name: str = None, customer_tax_id: str = None,
    customer_email: str = None,
) -> dict:
    """Generate an electronic invoice for a sale."""
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tenant_id).first()
    if not sale:
        raise ValueError("Venta no encontrada")

    # Check if already invoiced
    existing = ElectronicInvoice.query.filter_by(sale_id=sale_id).first()
    if existing:
        return _invoice_to_dict(existing)

    tenant = Tenant.query.get(tenant_id)
    prefix, number = _next_einvoice_number(tenant_id)

    invoice = ElectronicInvoice(
        tenant_id=tenant_id,
        sale_id=sale.id,
        created_by=created_by,
        invoice_number=number,
        prefix=prefix,
        status="draft",
        pta_provider=getattr(tenant, 'pta_provider', None) or "factus",
        subtotal=sale.subtotal,
        tax_amount=sale.tax_amount,
        total_amount=sale.total_amount,
        customer_name=customer_name or sale.customer_name or "Consumidor Final",
        customer_tax_id=customer_tax_id or sale.customer_tax_id or "222222222",
        customer_email=customer_email,
    )

    db.session.add(invoice)
    db.session.flush()

    # Build payload for PTA
    payload = _build_pta_payload(invoice, sale, tenant)

    # Try to send to PTA
    pta_api_key = getattr(tenant, 'pta_api_key', None)
    if pta_api_key:
        try:
            result = _send_to_pta(invoice, payload, pta_api_key)
            invoice.status = result.get("status", "sent")
            invoice.cufe = result.get("cufe")
            invoice.qr_code_url = result.get("qr_code_url")
            invoice.xml_url = result.get("xml_url")
            invoice.pdf_url = result.get("pdf_url")
            invoice.pta_request_id = result.get("request_id")
            invoice.pta_response = json.dumps(result)
            invoice.dian_response_code = result.get("dian_code")
            invoice.sent_at = datetime.now(timezone.utc)
            if result.get("status") == "accepted":
                invoice.accepted_at = datetime.now(timezone.utc)
        except Exception as e:
            invoice.status = "error"
            invoice.pta_response = json.dumps({"error": str(e)})
    else:
        # No PTA configured — generate in draft mode
        invoice.status = "draft"
        invoice.pta_response = json.dumps({
            "message": "PTA no configurado. Configure su proveedor tecnológico en Mi Negocio.",
            "payload": payload,
        })

    db.session.commit()
    return _invoice_to_dict(invoice)


def _build_pta_payload(invoice, sale, tenant):
    """Build the JSON payload that a PTA like Factus expects."""
    return {
        "document": {
            "type": "01",  # Factura de venta
            "number": invoice.invoice_number,
            "prefix": invoice.prefix,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "currency": "COP",
        },
        "supplier": {
            "tax_id": tenant.tax_id,
            "tax_id_check_digit": tenant.tax_id_check_digit or "",
            "name": tenant.name,
            "trade_name": tenant.trade_name or tenant.name,
            "address": tenant.address or "",
            "city": tenant.city or "Bogotá",
            "phone": tenant.phone or "",
            "email": tenant.email,
            "fiscal_regime": tenant.fiscal_regime,
        },
        "customer": {
            "tax_id": invoice.customer_tax_id or "222222222",
            "name": invoice.customer_name or "Consumidor Final",
            "email": invoice.customer_email or "",
        },
        "items": [
            {
                "description": item.product_name,
                "quantity": float(item.quantity),
                "unit_price": float(item.unit_price),
                "tax_rate": float(item.tax_rate),
                "subtotal": float(item.subtotal),
                "tax": float(item.tax_amount),
                "total": float(item.total),
            }
            for item in sale.items
        ],
        "totals": {
            "subtotal": float(invoice.subtotal),
            "tax": float(invoice.tax_amount),
            "total": float(invoice.total_amount),
        },
        "payment": {
            "method": sale.payments[0].method if sale.payments else "cash",
        },
    }


def _send_to_pta(invoice, payload, api_key):
    """Send invoice to PTA API. Returns response dict."""
    # For MVP: simulate PTA response
    # In production: replace with actual HTTP call to Factus/COLFACTURA API
    #
    # Example with Factus:
    # import httpx
    # resp = httpx.post(
    #     "https://api.factus.com.co/v1/invoices",
    #     json=payload,
    #     headers={"Authorization": f"Bearer {api_key}"},
    # )
    # return resp.json()

    # Simulated response for development
    cufe = str(uuid.uuid4()).replace("-", "")
    return {
        "status": "accepted",
        "cufe": cufe,
        "qr_code_url": f"https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey={cufe}",
        "xml_url": None,
        "pdf_url": None,
        "request_id": str(uuid.uuid4()),
        "dian_code": "00",
        "message": "Factura aceptada por DIAN (simulación desarrollo)",
    }


def generate_credit_note_invoice(
    tenant_id: str, credit_note_id: str, created_by: str,
) -> dict:
    """Generate an electronic credit note (NC tipo 91) for DIAN."""
    cn = CreditNote.query.filter_by(id=credit_note_id, tenant_id=tenant_id).first()
    if not cn:
        raise ValueError("Nota crédito no encontrada")

    # Check if already invoiced
    existing = ElectronicInvoice.query.filter_by(credit_note_id=credit_note_id).first()
    if existing:
        return _invoice_to_dict(existing)

    # Find original invoice for billing reference
    original_invoice = ElectronicInvoice.query.filter_by(
        sale_id=cn.sale_id, document_type="01"
    ).first()

    tenant = Tenant.query.get(tenant_id)
    prefix = "NC"
    last = (
        db.session.query(func.max(ElectronicInvoice.invoice_number))
        .filter(ElectronicInvoice.tenant_id == tenant_id,
                ElectronicInvoice.invoice_number.like(f"{prefix}%"))
        .scalar()
    )
    seq = int(last.replace(prefix, '')) + 1 if last else 1
    number = f"{prefix}{seq:06d}"

    invoice = ElectronicInvoice(
        tenant_id=tenant_id,
        sale_id=cn.sale_id,
        credit_note_id=cn.id,
        created_by=created_by,
        document_type="91",
        invoice_number=number,
        prefix=prefix,
        status="draft",
        pta_provider=getattr(tenant, 'pta_provider', None) or "factus",
        subtotal=cn.subtotal,
        tax_amount=cn.tax_amount,
        total_amount=cn.total_amount,
        customer_name=None,
        customer_tax_id=None,
    )

    db.session.add(invoice)
    db.session.flush()

    # Build NC payload
    payload = {
        "document": {
            "type": "91",  # Nota Crédito
            "number": number,
            "prefix": prefix,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "currency": "COP",
        },
        "billing_reference": {
            "number": original_invoice.invoice_number if original_invoice else None,
            "cufe": original_invoice.cufe if original_invoice else None,
        },
        "reason": cn.reason,
        "items": [
            {
                "description": item.product_name,
                "quantity": float(item.quantity),
                "unit_price": float(item.unit_price),
                "tax_rate": float(item.tax_rate),
                "subtotal": float(item.subtotal),
                "tax": float(item.tax_amount),
                "total": float(item.total),
            }
            for item in cn.items
        ],
        "totals": {
            "subtotal": float(cn.subtotal),
            "tax": float(cn.tax_amount),
            "total": float(cn.total_amount),
        },
    }

    # Send to PTA (simulated for now)
    pta_api_key = getattr(tenant, 'pta_api_key', None)
    if pta_api_key:
        try:
            result = _send_to_pta(invoice, payload, pta_api_key)
            invoice.status = result.get("status", "sent")
            invoice.cufe = result.get("cufe")
            invoice.pta_request_id = result.get("request_id")
            invoice.pta_response = json.dumps(result)
            invoice.dian_response_code = result.get("dian_code")
            invoice.sent_at = datetime.now(timezone.utc)
            if result.get("status") == "accepted":
                invoice.accepted_at = datetime.now(timezone.utc)
        except Exception as e:
            invoice.status = "error"
            invoice.pta_response = json.dumps({"error": str(e)})
    else:
        invoice.status = "draft"
        invoice.pta_response = json.dumps({"message": "PTA no configurado", "payload": payload})

    db.session.commit()
    return _invoice_to_dict(invoice)


def list_invoices(tenant_id: str, page: int = 1, per_page: int = 20) -> dict:
    """List electronic invoices."""
    q = ElectronicInvoice.query.filter_by(tenant_id=tenant_id)
    total = q.count()
    invoices = q.order_by(ElectronicInvoice.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return {
        "data": [_invoice_to_dict(i) for i in invoices],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "has_next": page * per_page < total,
        },
    }


def _invoice_to_dict(inv: ElectronicInvoice) -> dict:
    return {
        "id": str(inv.id),
        "invoice_number": inv.invoice_number,
        "document_type": inv.document_type,
        "prefix": inv.prefix,
        "cufe": inv.cufe,
        "qr_code_url": inv.qr_code_url,
        "pdf_url": inv.pdf_url,
        "status": inv.status,
        "pta_provider": inv.pta_provider,
        "dian_response_code": inv.dian_response_code,
        "subtotal": float(inv.subtotal),
        "tax_amount": float(inv.tax_amount),
        "total_amount": float(inv.total_amount),
        "customer_name": inv.customer_name,
        "customer_tax_id": inv.customer_tax_id,
        "created_at": inv.created_at.isoformat(),
        "sent_at": inv.sent_at.isoformat() if inv.sent_at else None,
        "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
    }
