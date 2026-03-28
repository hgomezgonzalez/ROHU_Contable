"""Electronic invoicing models — DIAN Colombia via PTA."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.extensions import db


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class ElectronicInvoice(db.Model):
    """Electronic invoice sent to DIAN via PTA (Proveedor Tecnológico Autorizado)."""

    __tablename__ = "electronic_invoices"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tenants.id"), nullable=False)
    sale_id = db.Column(UUID(as_uuid=True), db.ForeignKey("sales.id"), nullable=True)
    credit_note_id = db.Column(UUID(as_uuid=True), db.ForeignKey("credit_notes.id"), nullable=True)
    created_by = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    document_type = db.Column(db.String(5), nullable=False, default="01")  # 01=Factura, 91=NC, 92=ND

    # DIAN fields
    invoice_number = db.Column(db.String(30), nullable=False)
    prefix = db.Column(db.String(10))
    cufe = db.Column(db.String(200))  # Código Único de Factura Electrónica
    qr_code_url = db.Column(db.Text)
    xml_url = db.Column(db.Text)
    pdf_url = db.Column(db.Text)

    # Status
    status = db.Column(db.String(20), nullable=False, default="draft")
    # draft → sent → accepted / rejected

    # PTA response
    pta_provider = db.Column(db.String(50))  # factus, colfactura, etc.
    pta_request_id = db.Column(db.String(100))
    pta_response = db.Column(db.Text)  # JSON response from PTA
    dian_response_code = db.Column(db.String(10))

    # Amounts (snapshot from sale)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False)

    # Customer
    customer_name = db.Column(db.String(255))
    customer_tax_id = db.Column(db.String(20))
    customer_email = db.Column(db.String(255))

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    sent_at = db.Column(db.DateTime(timezone=True))
    accepted_at = db.Column(db.DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_einvoice_tenant_number"),
        Index("idx_einvoice_sale", "sale_id"),
        Index("idx_einvoice_status", "tenant_id", "status"),
    )

    def __repr__(self):
        return f"<EInvoice {self.invoice_number} ({self.status})>"
