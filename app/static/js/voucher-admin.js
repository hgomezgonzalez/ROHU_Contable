/**
 * Voucher Admin — Visual card-based UI with ROHU corporate modals.
 */
const API = "/api/v1/vouchers";
let currentPage = 1;
let voucherTypesMap = {};
let redeemScanner = null;

document.addEventListener("DOMContentLoaded", () => { loadStats(); loadTypes(); });

function switchTab(tab) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
  document.querySelector(`[data-tab="${tab}"]`).classList.add("active");
  document.getElementById(`tab-${tab}`).style.display = "block";
  if (tab === "vouchers") loadVouchers();
}

function authHeaders() { return { Authorization: "Bearer " + (localStorage.getItem("access_token") || "") }; }

// ── Stats ───────────────────────────────────────────────────────
async function loadStats() {
  try {
    const r = (await (await fetch(`${API}/stats`, { headers: authHeaders() })).json());
    if (!r.success) return;
    const d = r.data;
    document.getElementById("stat-circulation").textContent = "$" + Math.round(d.total_in_circulation).toLocaleString("es-CO");
    document.getElementById("stat-sold").textContent = (d.by_status?.sold?.count || 0) + (d.by_status?.partially_redeemed?.count || 0);
    document.getElementById("stat-redeemed").textContent = d.by_status?.redeemed?.count || 0;
    document.getElementById("stat-expired").textContent = d.by_status?.expired?.count || 0;
  } catch (e) { console.error(e); }
}

// ── Voucher Types (card grid) ───────────────────────────────────
async function loadTypes() {
  try {
    const r = (await (await fetch(`${API}/types?include_inactive=true`, { headers: authHeaders() })).json());
    if (!r.success) return;
    voucherTypesMap = {};
    r.data.forEach(vt => { voucherTypesMap[vt.id] = vt; });

    const grid = document.getElementById("types-grid");
    if (!r.data.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-light);">
        No hay tipos de bono. Cree el primero con el boton de arriba.</div>`;
      return;
    }

    grid.innerHTML = r.data.map(vt => {
      const color = vt.color_hex || "#1E3A8A";
      const badge = vt.status === "active"
        ? '<span style="background:rgba(255,255,255,0.25);padding:2px 10px;border-radius:10px;font-size:10px;">Activo</span>'
        : '<span style="background:rgba(0,0,0,0.2);padding:2px 10px;border-radius:10px;font-size:10px;">Inactivo</span>';
      return `
        <div class="type-card">
          <div class="type-header" style="background:linear-gradient(135deg, ${color}, ${color}cc);">
            <div style="display:flex;justify-content:space-between;align-items:start;position:relative;z-index:1;">
              <div>
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;opacity:0.8;">Bono de Descuento</div>
                <div style="font-size:28px;font-weight:800;margin:4px 0;">$${Math.round(vt.face_value).toLocaleString("es-CO")}</div>
                <div style="font-size:14px;font-weight:600;">${esc(vt.name)}</div>
              </div>
              ${badge}
            </div>
          </div>
          <div style="padding:14px 20px;">
            <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-light);margin-bottom:12px;">
              <span>Vigencia: ${vt.validity_days} dias</span>
              <span>Emitidos: ${vt.issued_count}${vt.max_issuable ? "/" + vt.max_issuable : ""}</span>
            </div>
            <div style="display:flex;gap:6px;">
              <button class="btn btn-sm btn-primary" style="flex:1;" onclick="showEmitPopup('${vt.id}')" ${vt.can_issue ? "" : "disabled"}>Emitir Bonos</button>
              <button class="btn btn-sm btn-outline" onclick="confirmDeleteType('${vt.id}','${esc(vt.name)}')">Eliminar</button>
            </div>
          </div>
        </div>`;
    }).join("");
  } catch (e) { console.error(e); }
}

// ── Create Type (rohuPrompt-style popup) ────────────────────────
async function showCreateTypePopup() {
  // Build a custom modal using the rohu modal system style
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;animation:rohuFadeIn 0.2s ease;";

  overlay.innerHTML = `
    <div style="background:white;border-radius:16px;width:100%;max-width:440px;box-shadow:0 25px 60px rgba(0,0,0,0.25);animation:rohuSlideUp 0.25s ease;overflow:hidden;">
      <div style="height:4px;background:linear-gradient(90deg,#1E3A8A,#10B981,#06B6D4);"></div>
      <div style="padding:24px;">
        <div style="text-align:center;margin-bottom:16px;">
          <div style="width:56px;height:56px;border-radius:50%;background:#DBEAFE;display:flex;align-items:center;justify-content:center;margin:0 auto 8px;">
            <svg viewBox="0 0 24 24" fill="none" stroke="#1E3A8A" stroke-width="2" style="width:28px;height:28px;"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>
          </div>
          <div style="font-weight:700;font-size:16px;color:#1E3A8A;">Nuevo Tipo de Bono</div>
          <div style="font-size:12px;color:#64748B;">Define el valor, vigencia y apariencia del bono</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:12px;">
          <div><label style="font-size:12px;font-weight:600;color:#0F172A;">Nombre del bono *</label>
            <input type="text" id="vt-name" class="form-control" required placeholder="Ej: Bono Navidad $50.000" style="margin-top:4px;"></div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div><label style="font-size:12px;font-weight:600;color:#0F172A;">Valor (COP) *</label>
              <input type="number" id="vt-face-value" class="form-control" required min="1000" step="1000" placeholder="50000" style="margin-top:4px;"></div>
            <div><label style="font-size:12px;font-weight:600;color:#0F172A;">Vigencia (dias) *</label>
              <input type="number" id="vt-validity" class="form-control" required min="90" max="730" value="180" style="margin-top:4px;"></div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div><label style="font-size:12px;font-weight:600;color:#0F172A;">Cantidad maxima</label>
              <input type="number" id="vt-max-issuable" class="form-control" min="1" placeholder="Ilimitado" style="margin-top:4px;"></div>
            <div><label style="font-size:12px;font-weight:600;color:#0F172A;">Color del bono</label>
              <div style="display:flex;gap:6px;margin-top:4px;align-items:center;">
                <input type="color" id="vt-color" value="#1E3A8A" style="width:40px;height:36px;border:none;cursor:pointer;border-radius:6px;">
                <div id="vt-color-preview" style="flex:1;height:36px;border-radius:6px;background:#1E3A8A;"></div>
              </div>
            </div>
          </div>
        </div>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:20px;">
          <button class="btn btn-outline" onclick="this.closest('[style*=fixed]').remove()">Cancelar</button>
          <button class="btn btn-primary" id="btn-create-type" onclick="doCreateType(this)">Crear Tipo de Bono</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(overlay);
  const colorInput = overlay.querySelector("#vt-color");
  const preview = overlay.querySelector("#vt-color-preview");
  colorInput.addEventListener("input", () => { preview.style.background = colorInput.value; });
  overlay.querySelector("#vt-name").focus();
}

async function doCreateType(btn) {
  const overlay = btn.closest("[style*=fixed]");
  const data = {
    name: overlay.querySelector("#vt-name").value,
    face_value: Number(overlay.querySelector("#vt-face-value").value),
    validity_days: Number(overlay.querySelector("#vt-validity").value),
    color_hex: overlay.querySelector("#vt-color").value,
  };
  const maxIss = overlay.querySelector("#vt-max-issuable").value;
  if (maxIss) data.max_issuable = Number(maxIss);

  if (!data.name || !data.face_value) { await rohuAlert("Complete todos los campos obligatorios", "warning"); return; }

  btn.disabled = true; btn.textContent = "Creando...";
  try {
    const r = (await (await fetch(`${API}/types`, { method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" }, body: JSON.stringify(data) })).json());
    if (r.success) { overlay.remove(); loadTypes(); loadStats(); await rohuAlert("Tipo de bono creado correctamente", "success"); }
    else { await rohuAlert(r.error?.message || "Error al crear", "error"); btn.disabled = false; btn.textContent = "Crear Tipo de Bono"; }
  } catch (e) { await rohuAlert("Error de conexion", "error"); btn.disabled = false; btn.textContent = "Crear Tipo de Bono"; }
}

async function confirmDeleteType(id, name) {
  if (await rohuConfirm(`Desactivar <strong>${name}</strong>?<br><span style="font-size:12px;color:#64748B;">Los bonos emitidos seguiran siendo validos.</span>`, "Desactivar", "warning"))
    try { await fetch(`${API}/types/${id}`, { method: "DELETE", headers: authHeaders() }); loadTypes(); await rohuAlert("Tipo desactivado", "success"); } catch (e) {}
}

// ── Emit Vouchers (popup) ───────────────────────────────────────
async function showEmitPopup(typeId) {
  const vt = voucherTypesMap[typeId];
  if (!vt) return;
  const qty = await rohuPrompt(
    `Emitir bonos de <strong>${esc(vt.name)}</strong><br>Valor: <strong>$${Math.round(vt.face_value).toLocaleString("es-CO")}</strong><br><br>¿Cuantos bonos desea emitir?`,
    "Cantidad (1-200)", "1", "number"
  );
  if (!qty || Number(qty) < 1) return;

  try {
    const r = (await (await fetch(`${API}/emit`, { method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" }, body: JSON.stringify({ type_id: typeId, quantity: Number(qty) }) })).json());
    if (r.success) {
      loadTypes(); loadStats();
      const count = r.count || 1;
      await rohuAlert(`<strong>${count} bono(s)</strong> emitido(s) correctamente.<br><br><span style="font-size:12px;color:#64748B;">Vaya a "Inventario de Bonos" para ver las tarjetas, imprimirlas o enviarlas por email.</span>`, "success");
    } else { await rohuAlert(r.error?.message || "Error al emitir", "error"); }
  } catch (e) { await rohuAlert("Error de conexion", "error"); }
}

// ── Voucher Inventory (mini cards) ──────────────────────────────
async function loadVouchers(page) {
  currentPage = page || 1;
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams({ page: currentPage, per_page: 12 });
  if (status) params.append("status", status);

  try {
    const r = (await (await fetch(`${API}/?${params}`, { headers: authHeaders() })).json());
    if (!r.success) return;
    const grid = document.getElementById("vouchers-grid");

    if (!r.data.length) {
      grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-light);">No hay bonos con este filtro. Emita bonos desde la pestana "Tipos de Bono".</div>';
      return;
    }

    const statusColors = { issued: "#94A3B8", sold: "#3B82F6", partially_redeemed: "#F59E0B", redeemed: "#059669", expired: "#94A3B8", cancelled: "#EF4444" };
    const statusLabels = { issued: "Emitido", sold: "Activo", partially_redeemed: "Parcial", redeemed: "Redimido", expired: "Vencido", cancelled: "Cancelado" };

    grid.innerHTML = r.data.map(v => {
      const vt = voucherTypesMap[v.voucher_type_id] || {};
      const color = vt.color_hex || "#1E3A8A";
      const sc = statusColors[v.status] || "#94A3B8";
      return `
        <div class="voucher-mini-card" onclick="showDetail('${v.id}')">
          <div class="voucher-mini-header" style="background:linear-gradient(135deg,${color},${color}cc);">
            <div style="display:flex;justify-content:space-between;align-items:start;position:relative;z-index:1;">
              <div>
                <div style="font-size:9px;text-transform:uppercase;letter-spacing:1.5px;opacity:0.7;">Bono de Descuento</div>
                <div style="font-size:24px;font-weight:800;">$${Math.round(v.face_value).toLocaleString("es-CO")}</div>
              </div>
              <span style="background:${sc};color:white;padding:2px 8px;border-radius:10px;font-size:9px;font-weight:600;">${statusLabels[v.status] || v.status}</span>
            </div>
          </div>
          <div class="voucher-mini-body">
            <div style="font-family:monospace;font-size:11px;font-weight:700;letter-spacing:0.5px;color:#0F172A;margin-bottom:4px;">${esc(v.code)}</div>
            <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-light);">
              <span>${esc(vt.name || "")}</span>
              <span>Vence: ${v.expires_at ? v.expires_at.substring(0, 10) : "—"}</span>
            </div>
            ${v.remaining_balance < v.face_value ? `<div style="margin-top:6px;"><div style="background:#E2E8F0;border-radius:4px;height:4px;overflow:hidden;"><div style="background:#059669;height:100%;width:${Math.round((1 - v.remaining_balance / v.face_value) * 100)}%;border-radius:4px;"></div></div><div style="font-size:10px;color:#64748B;margin-top:2px;">Saldo: $${Math.round(v.remaining_balance).toLocaleString("es-CO")}</div></div>` : ""}
          </div>
        </div>`;
    }).join("");

    // Pagination
    const p = r.pagination, pagDiv = document.getElementById("vouchers-pagination");
    pagDiv.innerHTML = "";
    if (p.total > p.per_page) {
      const pages = Math.ceil(p.total / p.per_page);
      for (let i = 1; i <= pages; i++) {
        const b = document.createElement("button");
        b.textContent = i; b.className = `btn btn-sm ${i === p.page ? "btn-primary" : "btn-secondary"}`;
        b.onclick = () => loadVouchers(i); pagDiv.appendChild(b);
      }
    }
  } catch (e) { console.error(e); }
}

// ── Detail Modal ────────────────────────────────────────────────
async function showDetail(voucherId) {
  try {
    const [vR, hR] = await Promise.all([
      fetch(`${API}/${voucherId}`, { headers: authHeaders() }),
      fetch(`${API}/${voucherId}/history`, { headers: authHeaders() })
    ]);
    const v = (await vR.json()).data, hist = (await hR.json()).data || [];
    if (!v) return;
    const vt = voucherTypesMap[v.voucher_type_id] || {};
    const color = vt.color_hex || "#1E3A8A";
    const statusLabels = { issued: "Emitido", sold: "Activo", partially_redeemed: "Parcialmente usado", redeemed: "Usado", expired: "Vencido", cancelled: "Cancelado" };

    document.getElementById("detail-content").innerHTML = `
      <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px;">
        <!-- Mini card -->
        <div style="width:240px;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.12);flex-shrink:0;">
          <div style="background:linear-gradient(135deg,${color},${color}cc);padding:18px;color:white;">
            <div style="font-size:9px;text-transform:uppercase;letter-spacing:1.5px;opacity:0.7;">Bono de Descuento</div>
            <div style="font-size:26px;font-weight:800;">$${Math.round(v.face_value).toLocaleString("es-CO")}</div>
            <div style="font-size:12px;opacity:0.8;margin-top:2px;">${esc(vt.name || "")}</div>
          </div>
          <div style="padding:12px 18px;background:white;">
            <div style="font-family:monospace;font-size:11px;font-weight:700;letter-spacing:1px;margin-bottom:6px;">${esc(v.code)}</div>
            <div style="font-size:11px;color:var(--text-light);">Vence: ${v.expires_at ? v.expires_at.substring(0, 10) : "—"}</div>
          </div>
        </div>
        <!-- Info + Actions -->
        <div style="flex:1;min-width:200px;">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;">
            <div><span style="font-size:10px;color:var(--text-light);">Estado</span><br><strong style="font-size:13px;">${statusLabels[v.status] || v.status}</strong></div>
            <div><span style="font-size:10px;color:var(--text-light);">Saldo</span><br><strong style="font-size:13px;">$${Math.round(v.remaining_balance).toLocaleString("es-CO")}</strong></div>
            <div><span style="font-size:10px;color:var(--text-light);">Emitido</span><br><strong style="font-size:13px;">${v.issued_at ? v.issued_at.substring(0, 10) : "—"}</strong></div>
            <div><span style="font-size:10px;color:var(--text-light);">Comprador</span><br><strong style="font-size:13px;">${esc(v.buyer_name || "—")}</strong></div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn btn-sm btn-primary" onclick="openPrintPage('${v.id}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;vertical-align:middle;margin-right:3px;"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
              Ver Tarjeta
            </button>
            <button class="btn btn-sm" style="background:#059669;color:white;" onclick="promptSendEmail('${v.id}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;vertical-align:middle;margin-right:3px;"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
              Email
            </button>
          </div>
        </div>
      </div>
      ${hist.length ? `
      <h4 style="font-size:13px;margin-bottom:8px;color:var(--text-light);">Historial</h4>
      <div class="table-wrap"><table style="width:100%;font-size:12px;">
        <thead><tr><th>Fecha</th><th>Tipo</th><th>Monto</th><th>Saldo</th><th>Notas</th></tr></thead>
        <tbody>${hist.map(h => `<tr><td>${h.occurred_at.substring(0, 16).replace("T", " ")}</td><td><span class="badge badge-info" style="font-size:9px;">${h.transaction_type}</span></td><td>$${Math.round(Math.abs(h.amount_change)).toLocaleString("es-CO")}</td><td>$${Math.round(h.balance_after).toLocaleString("es-CO")}</td><td>${esc(h.notes || "—")}</td></tr>`).join("")}</tbody>
      </table></div>` : ""}`;

    document.getElementById("detail-overlay").style.display = "flex";
  } catch (e) { await rohuAlert("Error cargando detalle", "error"); }
}

// ── Print / Email ───────────────────────────────────────────────
function openPrintPage(id) {
  fetch(`${API}/${id}/print`, { method: "POST", headers: authHeaders() }).catch(() => {});
  window.open(`/app/vouchers/${id}/print?token=${encodeURIComponent(localStorage.getItem("access_token") || "")}`, "_blank");
}

async function promptSendEmail(id) {
  // Build custom send modal
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;animation:rohuFadeIn 0.2s ease;";
  overlay.innerHTML = `
    <div style="background:white;border-radius:16px;width:100%;max-width:420px;box-shadow:0 25px 60px rgba(0,0,0,0.25);animation:rohuSlideUp 0.25s ease;overflow:hidden;">
      <div style="height:4px;background:linear-gradient(90deg,#059669,#10B981,#06B6D4);"></div>
      <div style="padding:24px;">
        <div style="text-align:center;margin-bottom:16px;">
          <div style="width:56px;height:56px;border-radius:50%;background:#ECFDF5;display:flex;align-items:center;justify-content:center;margin:0 auto 8px;">
            <svg viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2" style="width:28px;height:28px;"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
          </div>
          <div style="font-weight:700;font-size:16px;color:#059669;">Enviar Bono por Email</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:10px;">
          <div><label style="font-size:12px;font-weight:600;">De parte de *</label>
            <input type="text" id="send-from" class="form-control" placeholder="Ej: Juan Perez" style="margin-top:4px;"></div>
          <div><label style="font-size:12px;font-weight:600;">Para *</label>
            <input type="text" id="send-to-name" class="form-control" placeholder="Ej: Maria Garcia" style="margin-top:4px;"></div>
          <div><label style="font-size:12px;font-weight:600;">Email del destinatario *</label>
            <input type="email" id="send-email" class="form-control" placeholder="correo@destinatario.com" style="margin-top:4px;"></div>
          <div><label style="font-size:12px;font-weight:600;">Mensaje (opcional)</label>
            <textarea id="send-msg" class="form-control" placeholder="Ej: Feliz cumpleanos!" rows="2" style="margin-top:4px;resize:vertical;"></textarea></div>
        </div>
        <div id="send-status" style="margin-top:10px;font-size:12px;text-align:center;"></div>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:16px;">
          <button class="btn btn-outline" onclick="this.closest('[style*=fixed]').remove()">Cancelar</button>
          <button class="btn btn-primary" style="background:#059669;" id="btn-do-send" onclick="doSendEmail('${id}',this)">Enviar Bono</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector("#send-from").focus();
}

async function doSendEmail(id, btn) {
  const overlay = btn.closest("[style*=fixed]");
  const fromName = overlay.querySelector("#send-from").value.trim();
  const toName = overlay.querySelector("#send-to-name").value.trim();
  const email = overlay.querySelector("#send-email").value.trim();
  const message = overlay.querySelector("#send-msg").value.trim();
  const statusEl = overlay.querySelector("#send-status");

  if (!fromName || !toName || !email) { statusEl.textContent = "Complete todos los campos obligatorios"; statusEl.style.color = "#EF4444"; return; }

  btn.disabled = true; btn.textContent = "Enviando...";
  statusEl.textContent = "Enviando bono..."; statusEl.style.color = "#3B82F6";

  try {
    const r = (await (await fetch(`${API}/${id}/send-email`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ email, from_name: fromName, to_name: toName, message })
    })).json());
    if (r.success) {
      overlay.remove();
      await rohuAlert(`Bono enviado correctamente a <strong>${esc(toName)}</strong> (${esc(email)})<br><br><span style="font-size:12px;color:#64748B;">De parte de: ${esc(fromName)}</span>`, "success");
    } else {
      statusEl.textContent = r.error?.message || "Error al enviar"; statusEl.style.color = "#EF4444";
      btn.disabled = false; btn.textContent = "Enviar Bono";
    }
  } catch (e) {
    statusEl.textContent = "Error de conexion"; statusEl.style.color = "#EF4444";
    btn.disabled = false; btn.textContent = "Enviar Bono";
  }
}

// ── Redeem Tab ──────────────────────────────────────────────────
async function validateRedeemCode() {
  const code = document.getElementById("redeem-code").value.trim().toUpperCase();
  if (!code) { await rohuAlert("Ingrese un codigo de bono", "warning"); return; }

  const resultDiv = document.getElementById("redeem-result");
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<div style="color:var(--text-light);padding:12px;">Verificando...</div>';

  try {
    const r = (await (await fetch(`${API}/validate`, { method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" }, body: JSON.stringify({ code }) })).json());
    if (!r.success) {
      resultDiv.innerHTML = `<div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;padding:16px;color:#DC2626;"><strong>Bono no valido</strong><br>${r.error?.message || "Codigo no encontrado"}</div>`;
      return;
    }
    const d = r.data;
    if (d.valid) {
      resultDiv.innerHTML = `
        <div style="background:#ECFDF5;border:1px solid #A7F3D0;border-radius:12px;padding:20px;text-align:center;">
          <div style="font-size:24px;margin-bottom:4px;">&#10003;</div>
          <div style="font-weight:700;color:#059669;font-size:16px;">Bono Valido</div>
          <div style="font-size:28px;font-weight:800;color:#0F172A;margin:8px 0;">$${Math.round(d.remaining_balance).toLocaleString("es-CO")}</div>
          <div style="font-size:12px;color:#64748B;">Saldo disponible</div>
          <div style="font-size:12px;color:#64748B;margin-top:6px;">Vence: ${d.expires_at ? d.expires_at.substring(0, 10) : "—"}</div>
          <div style="margin-top:12px;padding:10px;background:#F0FDF4;border-radius:8px;font-size:12px;color:#065F46;">
            Para aplicar este bono, use "Bono" como metodo de pago en el Punto de Venta al momento de cobrar.
          </div>
        </div>`;
    } else {
      resultDiv.innerHTML = `
        <div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:12px;padding:20px;text-align:center;">
          <div style="font-size:24px;margin-bottom:4px;">&#10007;</div>
          <div style="font-weight:700;color:#DC2626;font-size:16px;">Bono No Valido</div>
          <div style="font-size:13px;color:#64748B;margin-top:8px;">${d.errors.join("<br>")}</div>
        </div>`;
    }
  } catch (e) {
    resultDiv.innerHTML = '<div style="color:#EF4444;padding:12px;">Error de conexion</div>';
  }
}

function startRedeemQRScan() {
  if (typeof Html5QrcodeScanner === "undefined") { rohuAlert("Scanner QR no disponible", "error"); return; }
  if (redeemScanner) { redeemScanner.clear(); redeemScanner = null; }
  redeemScanner = new Html5QrcodeScanner("qr-reader-redeem", { fps: 10, qrbox: { width: 250, height: 250 } });
  redeemScanner.render(code => {
    redeemScanner.clear(); redeemScanner = null;
    document.getElementById("redeem-code").value = code;
    validateRedeemCode();
  }, () => {});
}
