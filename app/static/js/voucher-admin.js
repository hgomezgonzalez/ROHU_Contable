/**
 * Voucher Admin — Management interface for voucher types and inventory.
 */

const API = '/api/v1/vouchers';
let currentPage = 1;

// ── Init ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadTypes();
});

// ── Tab Switching ───────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
  document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
  document.getElementById(`tab-${tab}`).style.display = 'block';
  if (tab === 'vouchers') loadVouchers();
}

// ── Stats ───────────────────────────────────────────────────────
async function loadStats() {
  try {
    const res = await fetch(`${API}/stats`, { headers: authHeaders() });
    const json = await res.json();
    if (!json.success) return;
    const d = json.data;
    const sold = d.by_status?.sold || { count: 0 };
    const partial = d.by_status?.partially_redeemed || { count: 0 };
    const redeemed = d.by_status?.redeemed || { count: 0 };
    const expired = d.by_status?.expired || { count: 0 };

    document.getElementById('stat-circulation').textContent =
      `$${Math.round(d.total_in_circulation).toLocaleString('es-CO')}`;
    document.getElementById('stat-sold').textContent = sold.count + (partial.count || 0);
    document.getElementById('stat-redeemed').textContent = redeemed.count;
    document.getElementById('stat-expired').textContent = expired.count;
  } catch (e) {
    console.error('Error loading stats:', e);
  }
}

// ── Voucher Types ───────────────────────────────────────────────
async function loadTypes() {
  try {
    const res = await fetch(`${API}/types?include_inactive=true`, { headers: authHeaders() });
    const json = await res.json();
    if (!json.success) return;

    const tbody = document.getElementById('types-tbody');
    tbody.innerHTML = '';

    json.data.forEach(vt => {
      const tr = document.createElement('tr');
      const statusBadge = vt.status === 'active'
        ? '<span class="badge badge-success">Activo</span>'
        : '<span class="badge badge-muted">Inactivo</span>';

      tr.innerHTML = `
        <td>${esc(vt.name)}</td>
        <td>$${Math.round(vt.face_value).toLocaleString('es-CO')}</td>
        <td>${vt.validity_days} dias</td>
        <td>${vt.issued_count}${vt.max_issuable ? '/' + vt.max_issuable : ''}</td>
        <td>${statusBadge}</td>
        <td>
          <button class="btn btn-sm btn-primary" onclick="showEmitModal('${vt.id}', '${esc(vt.name)}', ${vt.face_value})"
                  ${vt.can_issue ? '' : 'disabled'}>Emitir</button>
          <button class="btn btn-sm btn-secondary" onclick="deleteType('${vt.id}')">Eliminar</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error('Error loading types:', e);
  }
}

function showCreateTypeModal() {
  document.getElementById('create-type-form').reset();
  document.getElementById('create-type-modal').style.display = 'flex';
}

async function createVoucherType(e) {
  e.preventDefault();
  const data = {
    name: document.getElementById('vt-name').value,
    face_value: Number(document.getElementById('vt-face-value').value),
    validity_days: Number(document.getElementById('vt-validity').value),
    color_hex: document.getElementById('vt-color').value,
    design_template: 'default',
  };
  const maxIss = document.getElementById('vt-max-issuable').value;
  if (maxIss) data.max_issuable = Number(maxIss);

  try {
    const res = await fetch(`${API}/types`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const json = await res.json();
    if (json.success) {
      closeModal('create-type-modal');
      loadTypes();
      showToast('Tipo de bono creado');
    } else {
      showToast(json.error?.message || 'Error al crear', 'error');
    }
  } catch (e) {
    showToast('Error de conexion', 'error');
  }
  return false;
}

async function deleteType(typeId) {
  if (!confirm('Desactivar este tipo de bono?')) return;
  try {
    const res = await fetch(`${API}/types/${typeId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    const json = await res.json();
    if (json.success) {
      loadTypes();
      showToast('Tipo de bono desactivado');
    }
  } catch (e) {
    showToast('Error', 'error');
  }
}

// ── Emit Vouchers ───────────────────────────────────────────────
function showEmitModal(typeId, name, value) {
  document.getElementById('emit-type-id').value = typeId;
  document.getElementById('emit-type-info').textContent =
    `${name} — $${Math.round(value).toLocaleString('es-CO')}`;
  document.getElementById('emit-quantity').value = 1;
  document.getElementById('emit-modal').style.display = 'flex';
}

async function emitVouchers(e) {
  e.preventDefault();
  const typeId = document.getElementById('emit-type-id').value;
  const quantity = Number(document.getElementById('emit-quantity').value);

  try {
    const res = await fetch(`${API}/emit`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ type_id: typeId, quantity }),
    });
    const json = await res.json();
    if (json.success) {
      closeModal('emit-modal');
      loadTypes();
      loadStats();
      const count = json.count || 1;
      showToast(`${count} bono(s) emitido(s)`);
    } else {
      showToast(json.error?.message || 'Error al emitir', 'error');
    }
  } catch (e) {
    showToast('Error de conexion', 'error');
  }
  return false;
}

// ── Voucher Inventory ───────────────────────────────────────────
async function loadVouchers(page) {
  currentPage = page || 1;
  const status = document.getElementById('filter-status').value;
  const params = new URLSearchParams({ page: currentPage, per_page: 20 });
  if (status) params.append('status', status);

  try {
    const res = await fetch(`${API}/?${params}`, { headers: authHeaders() });
    const json = await res.json();
    if (!json.success) return;

    const tbody = document.getElementById('vouchers-tbody');
    tbody.innerHTML = '';

    json.data.forEach(v => {
      const statusLabels = {
        issued: '<span class="badge badge-info">Emitido</span>',
        sold: '<span class="badge badge-warning">Vendido</span>',
        partially_redeemed: '<span class="badge badge-warning">Parcial</span>',
        redeemed: '<span class="badge badge-success">Redimido</span>',
        expired: '<span class="badge badge-muted">Vencido</span>',
        cancelled: '<span class="badge badge-danger">Cancelado</span>',
      };

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><code>${esc(v.code)}</code></td>
        <td>${esc(v.voucher_type_id).substring(0, 8)}...</td>
        <td>$${Math.round(v.face_value).toLocaleString('es-CO')}</td>
        <td>$${Math.round(v.remaining_balance).toLocaleString('es-CO')}</td>
        <td>${statusLabels[v.status] || v.status}</td>
        <td>${v.expires_at ? v.expires_at.substring(0, 10) : '-'}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="showDetail('${v.id}')">Ver</button>
          <button class="btn btn-sm btn-primary" onclick="printVoucher('${v.id}')"
                  title="Imprimir">Imprimir</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    // Pagination
    const pag = json.pagination;
    const pagDiv = document.getElementById('vouchers-pagination');
    pagDiv.innerHTML = '';
    if (pag.total > pag.per_page) {
      const pages = Math.ceil(pag.total / pag.per_page);
      for (let i = 1; i <= pages; i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        btn.className = `btn btn-sm ${i === pag.page ? 'btn-primary' : 'btn-secondary'}`;
        btn.onclick = () => loadVouchers(i);
        pagDiv.appendChild(btn);
      }
    }
  } catch (e) {
    console.error('Error loading vouchers:', e);
  }
}

// ── Detail ──────────────────────────────────────────────────────
async function showDetail(voucherId) {
  try {
    const [vRes, hRes] = await Promise.all([
      fetch(`${API}/${voucherId}`, { headers: authHeaders() }),
      fetch(`${API}/${voucherId}/history`, { headers: authHeaders() }),
    ]);
    const vJson = await vRes.json();
    const hJson = await hRes.json();

    if (!vJson.success) return;
    const v = vJson.data;
    const history = hJson.success ? hJson.data : [];

    let historyHtml = history.map(h => `
      <tr>
        <td>${h.occurred_at.substring(0, 16).replace('T', ' ')}</td>
        <td>${h.transaction_type}</td>
        <td>$${Math.round(Math.abs(h.amount_change)).toLocaleString('es-CO')}</td>
        <td>$${Math.round(h.balance_after).toLocaleString('es-CO')}</td>
        <td>${esc(h.notes || '-')}</td>
      </tr>
    `).join('');

    document.getElementById('detail-content').innerHTML = `
      <div class="detail-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">
        <div><strong>Codigo:</strong> <code>${esc(v.code)}</code></div>
        <div><strong>Estado:</strong> ${v.status}</div>
        <div><strong>Valor nominal:</strong> $${Math.round(v.face_value).toLocaleString('es-CO')}</div>
        <div><strong>Saldo:</strong> $${Math.round(v.remaining_balance).toLocaleString('es-CO')}</div>
        <div><strong>Emitido:</strong> ${v.issued_at ? v.issued_at.substring(0, 10) : '-'}</div>
        <div><strong>Vence:</strong> ${v.expires_at ? v.expires_at.substring(0, 10) : '-'}</div>
        <div><strong>Vendido:</strong> ${v.sold_at ? v.sold_at.substring(0, 10) : '-'}</div>
        <div><strong>Comprador:</strong> ${esc(v.buyer_name || '-')}</div>
      </div>
      <h3>Historial de Movimientos</h3>
      <table class="data-table">
        <thead><tr><th>Fecha</th><th>Tipo</th><th>Monto</th><th>Saldo</th><th>Notas</th></tr></thead>
        <tbody>${historyHtml || '<tr><td colspan="5">Sin movimientos</td></tr>'}</tbody>
      </table>
    `;
    document.getElementById('detail-modal').style.display = 'flex';
  } catch (e) {
    showToast('Error cargando detalle', 'error');
  }
}

// ── Print ───────────────────────────────────────────────────────
async function printVoucher(voucherId) {
  try {
    // Record print event
    await fetch(`${API}/${voucherId}/print`, {
      method: 'POST',
      headers: authHeaders(),
    });
    // Open print window
    window.open(`/app/vouchers/${voucherId}/print`, '_blank', 'width=350,height=600');
  } catch (e) {
    showToast('Error al imprimir', 'error');
  }
}

// ── Helpers ─────────────────────────────────────────────────────
function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

function authHeaders() {
  const token = localStorage.getItem('access_token') || '';
  return { 'Authorization': `Bearer ${token}` };
}

function showToast(message, type) {
  if (window.rohuToast) {
    window.rohuToast(message, type);
  } else {
    alert(message);
  }
}
