"""Voucher print service — QR generation and print data builder."""

import base64
import io
from datetime import datetime, timezone


def generate_voucher_qr_image(voucher_code: str) -> bytes:
    """Generate a QR code image as PNG bytes."""
    try:
        import qrcode

        qr = qrcode.QRCode(version=1, box_size=10, border=4, error_correction=qrcode.constants.ERROR_CORRECT_H)
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


def build_voucher_print_data(
    voucher: dict,
    tenant: dict,
    color_hex: str = "#1E3A8A",
    from_name: str = "",
    to_name: str = "",
    message: str = "",
) -> dict:
    """Build all data needed to render a voucher card for printing/email."""
    issuer_name = tenant.get("trade_name") or tenant.get("name", "")
    issuer_nit = tenant.get("tax_id", "")

    disclaimer = (
        f"Este bono es emitido por {issuer_name} "
        f"(NIT: {issuer_nit}). "
        f"Válido hasta {voucher.get('expires_at', '')[:10]}. "
        f"Canjeable únicamente en {issuer_name}. "
        f"No tiene valor de cambio en efectivo salvo política expresa del emisor."
    )

    # Use tenant logo or ROHU default
    logo_url = tenant.get("logo_url", "")

    return {
        "code": voucher["code"],
        "face_value": voucher["face_value"],
        "face_value_formatted": f"${voucher['face_value']:,.0f}",
        "status": voucher["status"],
        "remaining_balance": voucher.get("remaining_balance", voucher["face_value"]),
        "issued_at": voucher.get("issued_at", ""),
        "expires_at": voucher.get("expires_at", ""),
        "expires_at_short": voucher.get("expires_at", "")[:10] if voucher.get("expires_at") else "",
        "qr_base64": generate_voucher_qr_base64(voucher["code"]),
        "issuer_name": issuer_name,
        "issuer_nit": issuer_nit,
        "issuer_address": tenant.get("address", ""),
        "issuer_phone": tenant.get("phone", ""),
        "logo_url": logo_url,
        "color_hex": color_hex,
        "from_name": from_name,
        "to_name": to_name,
        "gift_message": message,
        "disclaimer": disclaimer,
        "print_timestamp": datetime.now(timezone.utc).isoformat(),
    }
