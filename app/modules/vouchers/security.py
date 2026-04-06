"""Voucher code generation and HMAC verification.

Code format: {TENANT_PREFIX}-{RANDOM_PAYLOAD_10}-{HMAC_CHECKSUM_4}
Example:     ROH01-K7M2P9X4N1-A3F7

The HMAC binds the code to the tenant, preventing cross-tenant reuse.
Verification happens BEFORE any DB query to reject forgeries cheaply.
"""

import hashlib
import hmac
import os
import secrets

# Crockford Base32: excludes I, L, O, U to avoid visual confusion
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

MAX_CODE_GENERATION_RETRIES = 5


def _get_hmac_secret() -> str:
    secret = os.environ.get("VOUCHER_HMAC_SECRET", "")
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "VOUCHER_HMAC_SECRET must be set and at least 32 characters. "
            'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return secret


def _encode_crockford(data: bytes, length: int) -> str:
    """Encode bytes to Crockford Base32 of exact length."""
    value = int.from_bytes(data, "big")
    result = []
    for _ in range(length):
        result.append(CROCKFORD_ALPHABET[value % 32])
        value //= 32
    return "".join(reversed(result))


def _compute_checksum(tenant_id: str, payload: str) -> str:
    """Compute HMAC-SHA256 checksum truncated to 4 Crockford chars."""
    message = f"{tenant_id}:{payload}".encode("utf-8")
    mac = hmac.new(_get_hmac_secret().encode("utf-8"), message, hashlib.sha256).digest()
    return _encode_crockford(mac[:3], 4)


def _tenant_prefix(tenant_id: str) -> str:
    """First 5 uppercase alphanumeric chars of tenant_id."""
    cleaned = "".join(c for c in str(tenant_id).upper() if c.isalnum())
    return cleaned[:5].ljust(5, "0")


def generate_voucher_code(tenant_id: str) -> str:
    """Generate a cryptographically signed, non-predictable voucher code.

    Returns a string like 'ROH01-K7M2P9X4N1-A3F7'.
    """
    prefix = _tenant_prefix(tenant_id)
    raw_random = secrets.token_bytes(8)
    payload = _encode_crockford(raw_random, 10)
    checksum = _compute_checksum(str(tenant_id), payload)
    return f"{prefix}-{payload}-{checksum}"


def verify_voucher_code_format(code: str, tenant_id: str) -> bool:
    """Verify HMAC signature BEFORE querying the database.

    Rejects forgeries at the API layer without a DB round-trip.
    Returns True if the code format and HMAC are valid.
    """
    parts = code.upper().replace(" ", "").split("-")
    if len(parts) != 3:
        return False

    prefix, payload, provided_checksum = parts
    if len(payload) != 10 or len(provided_checksum) != 4:
        return False

    # Verify all chars are in Crockford alphabet
    valid_chars = set(CROCKFORD_ALPHABET)
    if not all(c in valid_chars for c in payload):
        return False
    if not all(c in valid_chars for c in provided_checksum):
        return False

    expected_checksum = _compute_checksum(str(tenant_id), payload)
    return hmac.compare_digest(provided_checksum, expected_checksum)
