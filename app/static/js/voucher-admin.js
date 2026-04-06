/**
 * Voucher Admin — Management interface with ROHU corporate modals.
 */

const API = "/api/v1/vouchers";
let currentPage = 1;
let voucherTypesMap = {};

// ── Init ────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadStats();
  loadTypes();
});

// ── Tab Switching ───────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((c) => (c.style.display = "none"));
  document.querySelector(`[data-tab="${tab}"]`).classList.add("active");
  document.getElementById(`tab-${tab}`).style.display = "block";
  if (tab === "vouchers") loadVouchers();
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

    document.getElementById("stat-circulation").textContent = `$${Math.round(d.total_in_circulation).toLocaleString("es-CO")}`;
    document.getElementById("stat-sold").textContent = sold.count + (partial.count || 0);
    document.getElementById("stat-redeemed").textContent = redeemed.count;
    document.getElementById("stat-expired").textContent = expired.count;
  } catch (e) {
    console.error("Error loading stats:", e);
  }
}

// ── Voucher Types ───────────────────────────────────────────────
async function loadTypes() {
  try {
    const res = await fetch(`${API}/types?include_inactive=true`, { headers: authHeaders() });
    const json = await res.json();
    if (!json.success) return;

    // Build type map for inventory table
    voucherTypesMap = {};
    json.data.forEach((vt) => {
      voucherTypesMap[vt.id] = vt.name;
    });

    const tbody = document.getElementById("types-tbody");
    tbody.innerHTML = "";

    json.data.forEach((vt) => {
      const statusBadge =
        vt.status === "active"
          ? '<span class="badge badge-success">Activo</span>'
          : '<span class="badge badge-muted">Inactivo</span>';

      const colorDot = vt.color_hex
        ? `<span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${esc(vt.color_hex)};margin-right:6px;vertical-align:middle;"></span>`
        : "";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${colorDot}${esc(vt.name)}</td>
        <td>$${Math.round(vt.face_value).toLocaleString("es-CO")}</td>
        <td>${vt.validity_days} dias</td>
        <td>${vt.issued_count}${vt.max_issuable ? "/" + vt.max_issuable : ""}</td>
        <td>${statusBadge}</td>
        <td>
          <button class="btn btn-sm btn-primary" onclick="showEmitModal('${vt.id}', '${esc(vt.name)}', ${vt.face_value})" ${vt.can_issue ? "" : "disabled"}>Emitir</button>
          <button class="btn btn-sm btn-outline" onclick="confirmDeleteType('${vt.id}', '${esc(vt.name)}')">Eliminar</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Error loading types:", e);
  }
}

function showCreateTypeModal() {
  document.getElementById("create-type-form").reset();
  document.getElementById("create-type-modal").style.display = "flex";
}

async function createVoucherType(e) {
  e.preventDefault();
  const data = {
    name: document.getElementById("vt-name").value,
    face_value: Number(document.getElementById("vt-face-value").value),
    validity_days: Number(document.getElementById("vt-validity").value),
    color_hex: document.getElementById("vt-color").value,
    design_template: "default",
  };
  const maxIss = document.getElementById("vt-max-issuable").value;
  if (maxIss) data.max_issuable = Number(maxIss);

  try {
    const res = await fetch(`${API}/types`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const json = await res.json();
    if (json.success) {
      closeModal("create-type-modal");
      loadTypes();
      await rohuAlert("Tipo de bono creado correctamente", "success");
    } else {
      await rohuAlert(json.error?.message || "Error al crear tipo de bono", "error");
    }
  } catch (e) {
    await rohuAlert("Error de conexion", "error");
  }
  return false;
}

async function confirmDeleteType(typeId, typeName) {
  const ok = await rohuConfirm(
    `¿Desactivar el tipo de bono <strong>${typeName}</strong>?<br><br><span style="font-size:12px;color:#64748B;">Los bonos ya emitidos de este tipo seguiran siendo validos.</span>`,
    "Desactivar",
    "warning"
  );
  if (!ok) return;

  try {
    const res = await fetch(`${API}/types/${typeId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    const json = await res.json();
    if (json.success) {
      loadTypes();
      await rohuAlert("Tipo de bono desactivado", "success");
    }
  } catch (e) {
    await rohuAlert("Error al desactivar", "error");
  }
}

// ── Emit Vouchers ───────────────────────────────────────────────
function showEmitModal(typeId, name, value) {
  document.getElementById("emit-type-id").value = typeId;
  document.getElementById("emit-type-info").innerHTML =
    `<strong>${esc(name)}</strong> — $${Math.round(value).toLocaleString("es-CO")}`;
  document.getElementById("emit-quantity").value = 1;
  document.getElementById("emit-modal").style.display = "flex";
}

async function emitVouchers(e) {
  e.preventDefault();
  const typeId = document.getElementById("emit-type-id").value;
  const quantity = Number(document.getElementById("emit-quantity").value);

  try {
    const res = await fetch(`${API}/emit`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ type_id: typeId, quantity }),
    });
    const json = await res.json();
    if (json.success) {
      closeModal("emit-modal");
      loadTypes();
      loadStats();
      const count = json.count || 1;
      const firstCode = json.data?.code || (Array.isArray(json.data) ? json.data[0]?.code : "");
      await rohuAlert(
        `<strong>${count} bono(s)</strong> emitido(s) correctamente.` +
          (firstCode ? `<br><br>Primer codigo: <code style="font-size:14px;letter-spacing:1px;">${esc(firstCode)}</code>` : "") +
          `<br><br><span style="font-size:12px;color:#64748B;">Vaya a la pestana "Inventario de Bonos" para imprimir o enviar por email.</span>`,
        "success"
      );
    } else {
      await rohuAlert(json.error?.message || "Error al emitir", "error");
    }
  } catch (e) {
    await rohuAlert("Error de conexion", "error");
  }
  return false;
}

// ── Voucher Inventory ───────────────────────────────────────────
async function loadVouchers(page) {
  currentPage = page || 1;
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams({ page: currentPage, per_page: 20 });
  if (status) params.append("status", status);

  try {
    const res = await fetch(`${API}/?${params}`, { headers: authHeaders() });
    const json = await res.json();
    if (!json.success) return;

    const tbody = document.getElementById("vouchers-tbody");
    tbody.innerHTML = "";

    json.data.forEach((v) => {
      const statusLabels = {
        issued: '<span class="badge badge-info">Emitido</span>',
        sold: '<span class="badge badge-warning">Activo</span>',
        partially_redeemed: '<span class="badge badge-warning">Parcial</span>',
        redeemed: '<span class="badge badge-success">Redimido</span>',
        expired: '<span class="badge badge-muted">Vencido</span>',
        cancelled: '<span class="badge badge-danger">Cancelado</span>',
      };

      const typeName = voucherTypesMap[v.voucher_type_id] || "—";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code style="font-size:11px;letter-spacing:0.5px;">${esc(v.code)}</code></td>
        <td>${esc(typeName)}</td>
        <td>$${Math.round(v.face_value).toLocaleString("es-CO")}</td>
        <td>$${Math.round(v.remaining_balance).toLocaleString("es-CO")}</td>
        <td>${statusLabels[v.status] || v.status}</td>
        <td>${v.expires_at ? v.expires_at.substring(0, 10) : "—"}</td>
        <td style="white-space:nowrap;">
          <button class="btn btn-sm btn-secondary" onclick="showDetail('${v.id}')">Ver</button>
          <button class="btn btn-sm btn-primary" onclick="openPrintPage('${v.id}')">Tarjeta</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    if (!json.data.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-light);text-align:center;">No hay bonos con este filtro</td></tr>';
    }

    // Pagination
    const pag = json.pagination;
    const pagDiv = document.getElementById("vouchers-pagination");
    pagDiv.innerHTML = "";
    if (pag.total > pag.per_page) {
      const pages = Math.ceil(pag.total / pag.per_page);
      for (let i = 1; i <= pages; i++) {
        const btn = document.createElement("button");
        btn.textContent = i;
        btn.className = `btn btn-sm ${i === pag.page ? "btn-primary" : "btn-secondary"}`;
        btn.onclick = () => loadVouchers(i);
        pagDiv.appendChild(btn);
      }
    }
  } catch (e) {
    console.error("Error loading vouchers:", e);
  }
}

// ── Detail Modal ────────────────────────────────────────────────
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
    const typeName = voucherTypesMap[v.voucher_type_id] || "—";

    const statusLabels = {
      issued: "Emitido",
      sold: "Activo",
      partially_redeemed: "Parcialmente usado",
      redeemed: "Usado completamente",
      expired: "Vencido",
      cancelled: "Cancelado",
    };

    let historyHtml = history
      .map(
        (h) => `
      <tr>
        <td style="font-size:12px;">${h.occurred_at.substring(0, 16).replace("T", " ")}</td>
        <td><span class="badge badge-info" style="font-size:10px;">${esc(h.transaction_type)}</span></td>
        <td style="font-size:12px;">$${Math.round(Math.abs(h.amount_change)).toLocaleString("es-CO")}</td>
        <td style="font-size:12px;">$${Math.round(h.balance_after).toLocaleString("es-CO")}</td>
        <td style="font-size:12px;">${esc(h.notes || "—")}</td>
      </tr>
    `
      )
      .join("");

    document.getElementById("detail-content").innerHTML = `
      <div style="display:flex;gap:20px;margin-bottom:24px;flex-wrap:wrap;">
        <!-- Mini card preview -->
        <div style="width:260px;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.1);flex-shrink:0;">
          <div style="background:#1E3A8A;padding:16px;color:white;">
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;opacity:0.8;margin-bottom:4px;">Bono de Descuento</div>
            <div style="font-size:28px;font-weight:800;">$${Math.round(v.face_value).toLocaleString("es-CO")}</div>
          </div>
          <div style="padding:12px 16px;background:white;">
            <div style="font-family:monospace;font-size:12px;font-weight:700;letter-spacing:1px;color:#0F172A;margin-bottom:8px;">${esc(v.code)}</div>
            <div style="font-size:11px;color:#64748B;">Vence: ${v.expires_at ? v.expires_at.substring(0, 10) : "—"}</div>
          </div>
        </div>

        <!-- Info -->
        <div style="flex:1;min-width:200px;">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div><span style="font-size:11px;color:#64748B;">Estado</span><br><strong>${statusLabels[v.status] || v.status}</strong></div>
            <div><span style="font-size:11px;color:#64748B;">Tipo</span><br><strong>${esc(typeName)}</strong></div>
            <div><span style="font-size:11px;color:#64748B;">Saldo restante</span><br><strong>$${Math.round(v.remaining_balance).toLocaleString("es-CO")}</strong></div>
            <div><span style="font-size:11px;color:#64748B;">Comprador</span><br><strong>${esc(v.buyer_name || "—")}</strong></div>
            <div><span style="font-size:11px;color:#64748B;">Emitido</span><br><strong>${v.issued_at ? v.issued_at.substring(0, 10) : "—"}</strong></div>
            <div><span style="font-size:11px;color:#64748B;">Vendido</span><br><strong>${v.sold_at ? v.sold_at.substring(0, 10) : "—"}</strong></div>
          </div>
          <div style="display:flex;gap:8px;margin-top:16px;">
            <button class="btn btn-sm btn-primary" onclick="openPrintPage('${v.id}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;vertical-align:middle;margin-right:3px;"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
              Ver Tarjeta
            </button>
            <button class="btn btn-sm" style="background:#059669;color:white;" onclick="promptSendEmail('${v.id}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;vertical-align:middle;margin-right:3px;"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
              Enviar Email
            </button>
          </div>
        </div>
      </div>

      <h4 style="font-size:14px;margin-bottom:8px;">Historial de Movimientos</h4>
      <div class="table-wrap">
        <table class="data-table" style="font-size:13px;">
          <thead><tr><th>Fecha</th><th>Tipo</th><th>Monto</th><th>Saldo</th><th>Notas</th></tr></thead>
          <tbody>${historyHtml || '<tr><td colspan="5" style="text-align:center;color:#94A3B8;">Sin movimientos</td></tr>'}</tbody>
        </table>
      </div>
    `;
    document.getElementById("detail-modal").style.display = "flex";
  } catch (e) {
    await rohuAlert("Error cargando detalle del bono", "error");
  }
}

// ── Print / Card ────────────────────────────────────────────────
function openPrintPage(voucherId) {
  // Record print event
  fetch(`${API}/${voucherId}/print`, {
    method: "POST",
    headers: authHeaders(),
  }).catch(() => {});
  // Open card page with token for auth
  const token = localStorage.getItem("access_token") || "";
  window.open(`/app/vouchers/${voucherId}/print?token=${encodeURIComponent(token)}`, "_blank");
}

// ── Send Email ──────────────────────────────────────────────────
async function promptSendEmail(voucherId) {
  const email = await rohuPrompt(
    "Ingrese el email del destinatario para enviar el bono:",
    "correo@destinatario.com"
  );
  if (!email) return;

  try {
    const res = await fetch(`${API}/${voucherId}/send-email`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const json = await res.json();
    if (json.success) {
      await rohuAlert(`Bono enviado correctamente a <strong>${esc(email)}</strong>`, "success");
    } else {
      await rohuAlert(json.error?.message || "Error al enviar email", "error");
    }
  } catch (e) {
    await rohuAlert("Error de conexion al enviar email", "error");
  }
}

// ── Helpers ─────────────────────────────────────────────────────
function closeModal(id) {
  document.getElementById(id).style.display = "none";
}

function authHeaders() {
  const token = localStorage.getItem("access_token") || "";
  return { Authorization: `Bearer ${token}` };
}
