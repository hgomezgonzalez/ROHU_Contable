/**
 * Voucher POS Integration — Scan, validate, and apply vouchers at checkout.
 *
 * SECURITY: Voucher redemption is BLOCKED when offline.
 */

const VOUCHER_API = '/api/v1/vouchers';

// ── Voucher Validation (pre-checkout) ───────────────────────────
async function validateVoucherCode(code) {
  // Block if offline
  if (!navigator.onLine) {
    return {
      valid: false,
      errors: ['La redencion de bonos requiere conexion a internet. Use otro metodo de pago.'],
    };
  }

  const token = localStorage.getItem('access_token') || '';
  try {
    const res = await fetch(`${VOUCHER_API}/validate`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ code: code.toUpperCase().trim() }),
    });

    const json = await res.json();
    if (!json.success) {
      return {
        valid: false,
        errors: [json.error?.message || 'Bono no valido'],
      };
    }
    return json.data;
  } catch (e) {
    return {
      valid: false,
      errors: ['Error de conexion al validar el bono'],
    };
  }
}

// ── Apply Voucher to Cart ───────────────────────────────────────
function buildVoucherRedemptionPayload(code, amount) {
  return {
    code: code.toUpperCase().trim(),
    amount: amount,
    idempotency_key: crypto.randomUUID(),
  };
}

function buildVoucherSalePayload(code, buyerName, buyerIdDocument) {
  return {
    code: code.toUpperCase().trim(),
    buyer_name: buyerName || null,
    buyer_id_document: buyerIdDocument || null,
    idempotency_key: crypto.randomUUID(),
  };
}

// ── QR Scanner for Vouchers ─────────────────────────────────────
let voucherScanner = null;

function startVoucherScanner(containerId, onScan) {
  if (typeof Html5QrcodeScanner === 'undefined') {
    console.warn('html5-qrcode not loaded');
    return;
  }

  if (voucherScanner) {
    voucherScanner.clear();
  }

  voucherScanner = new Html5QrcodeScanner(containerId, {
    fps: 10,
    qrbox: { width: 250, height: 250 },
    rememberLastUsedCamera: true,
  });

  voucherScanner.render(
    (decodedText) => {
      voucherScanner.clear();
      voucherScanner = null;
      onScan(decodedText);
    },
    (error) => {
      // Scanning errors are normal — camera still searching
    }
  );
}

function stopVoucherScanner() {
  if (voucherScanner) {
    voucherScanner.clear();
    voucherScanner = null;
  }
}

// ── Voucher UI Helpers ──────────────────────────────────────────
function formatVoucherStatus(status) {
  const labels = {
    issued: 'Emitido',
    sold: 'Activo',
    partially_redeemed: 'Parcial',
    redeemed: 'Usado',
    expired: 'Vencido',
    cancelled: 'Cancelado',
  };
  return labels[status] || status;
}

function formatCOP(amount) {
  return `$${Math.round(amount).toLocaleString('es-CO')}`;
}

// ── Offline Guard ───────────────────────────────────────────────
function isVoucherRedemptionAllowed() {
  if (!navigator.onLine) {
    if (window.rohuToast) {
      window.rohuToast(
        'Los bonos requieren conexion a internet para ser redimidos.',
        'error'
      );
    }
    return false;
  }
  return true;
}
