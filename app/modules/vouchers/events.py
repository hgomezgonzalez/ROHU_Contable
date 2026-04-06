"""Voucher domain events — Outbox pattern compatible."""


# Event type constants
VOUCHER_EMITTED = "Vouchers.Voucher.Emitted"
VOUCHER_SOLD = "Vouchers.Voucher.Sold"
VOUCHER_REDEEMED = "Vouchers.Voucher.Redeemed"
VOUCHER_EXPIRED = "Vouchers.Voucher.Expired"
VOUCHER_CANCELLED = "Vouchers.Voucher.Cancelled"


def build_voucher_event(event_type: str, voucher: dict, **extra) -> dict:
    """Build a domain event payload for the outbox."""
    return {
        "event_type": event_type,
        "payload": {
            "voucher_id": voucher.get("id"),
            "tenant_id": voucher.get("tenant_id"),
            "code": voucher.get("code"),
            "face_value": voucher.get("face_value"),
            "remaining_balance": voucher.get("remaining_balance"),
            "status": voucher.get("status"),
            **extra,
        },
    }
