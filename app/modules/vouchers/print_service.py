"""Voucher print service — PDF/QR generation for thermal and A4 printers."""

import io
import base64
from datetime import datetime, timezone


def generate_voucher_qr_data(voucher_code: str) -> str:
    """Generate the data string to encode in QR code."""
    return voucher_code


def generate_voucher_qr_image(voucher_code: str) -> bytes:
    """Generate a QR code image as PNG bytes."""
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=10, border=4,
                           error_correction=qrcode.constants.ERROR_CORRECT_H)
        qr.add_data(voucher_code)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return b""


def generate_voucher_qr_base64(voucher_code: str) -> str:
    """Generate QR code as base64 string for embedding in HTML."""
    png_bytes = generate_voucher_qr_image(voucher_code)
    if png_bytes:
        return base64.b64encode(png_bytes).decode("utf-8")
    return ""


def build_voucher_print_data(voucher: dict, tenant: dict) -> dict:
    """
    Build all data needed to render a voucher for printing.

    Returns a dict with fields for the Jinja2 template.
    """
    disclaimer = (
        f"Este bono es emitido por {tenant.get('name', '')} "
        f"({tenant.get('nit', '')}). "
        f"Válido hasta {voucher.get('expires_at', '')[:10]}. "
        f"Canjeable únicamente en {tenant.get('name', '')}. "
        f"No tiene valor de cambio en efectivo salvo política expresa del emisor."
    )

    return {
        "code": voucher["code"],
        "face_value": voucher["face_value"],
        "face_value_formatted": f"${voucher['face_value']:,.0f}",
        "status": voucher["status"],
        "issued_at": voucher.get("issued_at", ""),
        "expires_at": voucher.get("expires_at", ""),
        "expires_at_short": voucher.get("expires_at", "")[:10] if voucher.get("expires_at") else "",
        "qr_base64": generate_voucher_qr_base64(voucher["code"]),
        "issuer_name": tenant.get("name", ""),
        "issuer_nit": tenant.get("nit", ""),
        "issuer_address": tenant.get("address", ""),
        "issuer_phone": tenant.get("phone", ""),
        "disclaimer": disclaimer,
        "print_timestamp": datetime.now(timezone.utc).isoformat(),
    }
