/**
 * Orders Admin — Create, manage, and close orders.
 */
const OAPI = "/api/v1/orders";
let currentPage = 1;

function authH() {
  return { Authorization: "Bearer " + (localStorage.getItem("access_token") || "") };
}

document.addEventListener("DOMContentLoaded", () => { loadStats(); loadActiveOrders(); });

function switchTab(tab) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
  document.querySelector(`[data-tab="${tab}"]`).classList.add("active");
  document.getElementById(`tab-${tab}`).style.display = "block";
  if (tab === "all") loadAllOrders();
}

// ── Stats ────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const r = await (await fetch(`${OAPI}/stats`, { headers: authH() })).json();
    if (!r.success) return;
    const d = r.data;
    document.getElementById("stat-active").textContent = d.active_count || 0;
    document.getElementById("stat-today").textContent = d.total_today || 0;
    document.getElementById("stat-closed").textContent = d.by_status?.closed || 0;
    document.getElementById("stat-cancelled").textContent = d.by_status?.cancelled || 0;
  } catch (e) { console.error(e); }
}

// ── Active Orders ────────────────────────────────────────────────
async function loadActiveOrders() {
  try {
    const r = await (await fetch(`${OAPI}?status=draft&per_page=50`, { headers: authH() })).json();
    const r2 = await (await fetch(`${OAPI}?status=confirmed&per_page=50`, { headers: authH() })).json();
    const r3 = await (await fetch(`${OAPI}?status=ready&per_page=50`, { headers: authH() })).json();

    const all = [...(r.data || []), ...(r2.data || []), ...(r3.data || [])];
    const grid = document.getElementById("active-orders");

    if (!all.length) {
      grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-light);">No hay pedidos activos. Cree uno con el boton de arriba.</div>';
      return;
    }

    grid.innerHTML = all.map(o => renderOrderCard(o)).join("");
  } catch (e) { console.error(e); }
}

async function loadAllOrders(page) {
  currentPage = page || 1;
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams({ page: currentPage, per_page: 12 });
  if (status) params.append("status", status);

  try {
    const r = await (await fetch(`${OAPI}?${params}`, { headers: authH() })).json();
    if (!r.success) return;
    const grid = document.getElementById("all-orders");
    if (!r.data.length) {
      grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-light);">Sin pedidos con este filtro</div>';
      return;
    }
    grid.innerHTML = r.data.map(o => renderOrderCard(o)).join("");
  } catch (e) { console.error(e); }
}

function renderOrderCard(o) {
  const COP = n => "$" + Math.round(n).toLocaleString("es-CO");
  const statusColors = { draft: "#94A3B8", confirmed: "#3B82F6", in_preparation: "#F59E0B", ready: "#059669", closed: "#6B7280", cancelled: "#EF4444", close_failed: "#DC2626" };
  const sc = statusColors[o.status] || "#94A3B8";
  const itemsPreview = o.items.slice(0, 3).map(i => `${Math.round(i.quantity)}x ${i.product_name}`).join(", ");
  const extra = o.items.length > 3 ? ` +${o.items.length - 3} mas` : "";

  return `
    <div class="order-card" onclick="showOrderDetail('${o.id}')">
      <div class="order-header status-${o.status}" style="background:${sc};">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:16px;font-weight:700;">${o.order_number}</span>
          <span style="font-size:11px;background:rgba(255,255,255,0.25);padding:2px 8px;border-radius:10px;">${o.status_label}</span>
        </div>
        ${o.table_number ? `<div style="font-size:12px;opacity:0.8;margin-top:2px;">Mesa ${o.table_number}</div>` : ""}
      </div>
      <div class="order-body">
        <div style="font-size:12px;color:var(--text-light);margin-bottom:6px;">${itemsPreview}${extra}</div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:16px;font-weight:700;">${COP(o.total_preview)}</span>
          <span style="font-size:11px;color:var(--text-light);">${o.created_at.substring(11, 16)}</span>
        </div>
        ${o.customer_name ? `<div style="font-size:11px;color:var(--text-light);margin-top:4px;">${o.customer_name}</div>` : ""}
      </div>
    </div>`;
}

// ── New Order Popup ──────────────────────────────────────────────
async function showNewOrderPopup() {
  // Load products first
  let products = [];
  try {
    const r = await (await fetch("/api/v1/inventory/products?per_page=100", { headers: authH() })).json();
    products = r.data || [];
  } catch (e) {}

  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;animation:rohuFadeIn 0.2s ease;";
  overlay.innerHTML = `
    <div style="background:white;border-radius:16px;width:100%;max-width:520px;max-height:90vh;overflow-y:auto;box-shadow:0 25px 60px rgba(0,0,0,0.25);animation:rohuSlideUp 0.25s ease;overflow:hidden;">
      <div style="height:4px;background:linear-gradient(90deg,#1E3A8A,#10B981,#06B6D4);"></div>
      <div style="padding:24px;">
        <div style="text-align:center;margin-bottom:16px;">
          <div style="font-weight:700;font-size:16px;color:#1E3A8A;">Nuevo Pedido</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
          <div><label style="font-size:12px;font-weight:600;">Mesa (opcional)</label>
            <input type="text" id="new-order-table" class="form-control" placeholder="Ej: 5" style="margin-top:4px;"></div>
          <div><label style="font-size:12px;font-weight:600;">Cliente (opcional)</label>
            <input type="text" id="new-order-customer" class="form-control" placeholder="Nombre" style="margin-top:4px;"></div>
        </div>
        <div style="margin-bottom:12px;">
          <label style="font-size:12px;font-weight:600;">Productos *</label>
          <input type="text" id="new-order-search" class="form-control" placeholder="Buscar producto..." style="margin-top:4px;" oninput="filterNewOrderProducts(this.value)">
        </div>
        <div id="new-order-products" style="max-height:200px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;margin-bottom:12px;">
          ${products.map(p => `
            <div class="new-order-product" data-id="${p.id}" data-name="${p.name}" data-price="${p.sale_price}" data-sku="${p.sku || ''}" style="padding:8px 12px;border-bottom:1px solid #F1F5F9;display:flex;justify-content:space-between;align-items:center;cursor:pointer;" onclick="addToNewOrder(this)">
              <div><strong style="font-size:13px;">${p.name}</strong><br><span style="font-size:11px;color:var(--text-light);">$${Math.round(p.sale_price).toLocaleString("es-CO")} · Stock: ${Math.round(p.stock_current)}</span></div>
              <button class="btn btn-sm btn-primary" style="padding:4px 10px;">+</button>
            </div>
          `).join("")}
        </div>
        <div id="new-order-items" style="margin-bottom:12px;"></div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <span style="font-size:14px;font-weight:700;">Total estimado:</span>
          <span id="new-order-total" style="font-size:18px;font-weight:700;color:var(--primary);">$0</span>
        </div>
        <div><label style="font-size:12px;font-weight:600;">Notas (opcional)</label>
          <textarea id="new-order-notes" class="form-control" rows="2" placeholder="Notas generales del pedido" style="margin-top:4px;"></textarea></div>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:16px;">
          <button class="btn btn-outline" onclick="this.closest('[style*=fixed]').remove()">Cancelar</button>
          <button class="btn btn-primary" id="btn-create-order" onclick="doCreateOrder(this)">Crear Pedido</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector("#new-order-search").focus();
  window._newOrderItems = [];
}

function filterNewOrderProducts(q) {
  const lower = q.toLowerCase();
  document.querySelectorAll(".new-order-product").forEach(el => {
    el.style.display = el.dataset.name.toLowerCase().includes(lower) || (el.dataset.sku || "").toLowerCase().includes(lower) ? "" : "none";
  });
}

function addToNewOrder(el) {
  const id = el.dataset.id, name = el.dataset.name, price = parseFloat(el.dataset.price);
  const existing = window._newOrderItems.find(i => i.product_id === id);
  if (existing) { existing.quantity++; } else { window._newOrderItems.push({ product_id: id, name, price, quantity: 1, notes: "" }); }
  renderNewOrderItems();
}

function renderNewOrderItems() {
  const container = document.getElementById("new-order-items");
  const COP = n => "$" + Math.round(n).toLocaleString("es-CO");
  let total = 0;
  container.innerHTML = window._newOrderItems.map((item, i) => {
    const sub = item.price * item.quantity;
    total += sub;
    return `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #F1F5F9;">
        <button onclick="window._newOrderItems[${i}].quantity=Math.max(1,window._newOrderItems[${i}].quantity-1);renderNewOrderItems();" style="width:24px;height:24px;border:1px solid var(--border);border-radius:4px;background:white;cursor:pointer;">-</button>
        <span style="font-weight:600;min-width:20px;text-align:center;">${item.quantity}</span>
        <button onclick="window._newOrderItems[${i}].quantity++;renderNewOrderItems();" style="width:24px;height:24px;border:1px solid var(--border);border-radius:4px;background:white;cursor:pointer;">+</button>
        <span style="flex:1;font-size:13px;">${item.name}</span>
        <span style="font-size:12px;color:var(--text-light);">${COP(sub)}</span>
        <button onclick="window._newOrderItems.splice(${i},1);renderNewOrderItems();" style="background:none;border:none;color:#EF4444;cursor:pointer;font-size:16px;">&times;</button>
      </div>`;
  }).join("");
  document.getElementById("new-order-total").textContent = COP(total);
}

async function doCreateOrder(btn) {
  if (!window._newOrderItems.length) { await rohuAlert("Agregue al menos un producto", "warning"); return; }
  btn.disabled = true; btn.textContent = "Creando...";

  const data = {
    items: window._newOrderItems.map(i => ({ product_id: i.product_id, quantity: i.quantity, notes: i.notes || null })),
    table_number: document.getElementById("new-order-table").value.trim() || null,
    customer_name: document.getElementById("new-order-customer").value.trim() || null,
    notes: document.getElementById("new-order-notes").value.trim() || null,
  };

  try {
    const r = await (await fetch(OAPI, { method: "POST", headers: { ...authH(), "Content-Type": "application/json" }, body: JSON.stringify(data) })).json();
    if (r.success) {
      btn.closest("[style*=fixed]").remove();
      loadActiveOrders(); loadStats();
      await rohuAlert(`Pedido <strong>${r.data.order_number}</strong> creado.<br><span style="font-size:12px;color:#64748B;">Confirme el pedido para enviarlo a cocina/alistamiento.</span>`, "success");
    } else {
      await rohuAlert(r.error?.message || "Error al crear pedido", "error");
      btn.disabled = false; btn.textContent = "Crear Pedido";
    }
  } catch (e) {
    await rohuAlert("Error de conexion", "error");
    btn.disabled = false; btn.textContent = "Crear Pedido";
  }
}

// ── Order Detail ─────────────────────────────────────────────────
async function showOrderDetail(orderId) {
  try {
    const r = await (await fetch(`${OAPI}/${orderId}`, { headers: authH() })).json();
    if (!r.success) return;
    const o = r.data;
    const COP = n => "$" + Math.round(n).toLocaleString("es-CO");
    const statusColors = { draft: "#94A3B8", confirmed: "#3B82F6", in_preparation: "#F59E0B", ready: "#059669", closed: "#6B7280", cancelled: "#EF4444" };

    let actions = "";
    if (o.status === "draft") actions = `<button class="btn btn-sm btn-primary" onclick="confirmOrder('${o.id}')">Confirmar Pedido</button> <button class="btn btn-sm btn-outline" style="color:#EF4444;" onclick="cancelOrder('${o.id}')">Cancelar</button>`;
    else if (o.status === "confirmed") actions = `<button class="btn btn-sm" style="background:#F59E0B;color:white;" onclick="changeStatus('${o.id}','in_preparation')">En Preparacion</button> <button class="btn btn-sm" style="background:#059669;color:white;" onclick="changeStatus('${o.id}','ready')">Marcar Listo</button> <button class="btn btn-sm btn-outline" style="color:#EF4444;" onclick="cancelOrder('${o.id}')">Cancelar</button>`;
    else if (o.status === "in_preparation") actions = `<button class="btn btn-sm" style="background:#059669;color:white;" onclick="changeStatus('${o.id}','ready')">Marcar Listo</button>`;
    else if (o.status === "ready" || o.status === "close_failed") actions = `<button class="btn btn-sm btn-primary" onclick="showClosePopup('${o.id}',${o.total_preview})">Cerrar y Cobrar</button> <button class="btn btn-sm btn-outline" style="color:#EF4444;" onclick="cancelOrder('${o.id}')">Cancelar</button>`;

    document.getElementById("detail-title").textContent = `Pedido ${o.order_number}`;
    document.getElementById("order-detail-content").innerHTML = `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:16px;">
        <span style="background:${statusColors[o.status] || '#94A3B8'};color:white;padding:4px 12px;border-radius:10px;font-size:12px;font-weight:600;">${o.status_label}</span>
        ${o.table_number ? `<span style="font-size:13px;color:var(--text-light);">Mesa ${o.table_number}</span>` : ""}
        ${o.customer_name ? `<span style="font-size:13px;color:var(--text-light);">· ${o.customer_name}</span>` : ""}
      </div>
      <div class="table-wrap"><table style="width:100%;font-size:13px;">
        <thead><tr><th>Cant</th><th>Producto</th><th>Precio</th><th>Subtotal</th><th>Notas</th></tr></thead>
        <tbody>${o.items.map(i => `<tr><td>${Math.round(i.quantity)}</td><td>${i.product_name}${i.added_after_confirmation ? ' <span style="color:#F59E0B;font-size:10px;">(agregado)</span>' : ""}</td><td>${COP(i.unit_price)}</td><td>${COP(i.subtotal)}</td><td style="font-size:11px;color:#64748B;">${i.notes || "—"}</td></tr>`).join("")}</tbody>
      </table></div>
      <div style="text-align:right;font-size:18px;font-weight:700;margin:12px 0;">Total: ${COP(o.total_preview)}</div>
      ${o.notes ? `<div style="padding:8px 12px;background:#FFFBEB;border-radius:6px;font-size:12px;color:#92400E;margin-bottom:12px;"><strong>Notas:</strong> ${o.notes}</div>` : ""}
      <div style="display:flex;gap:6px;flex-wrap:wrap;">${actions}</div>
    `;
    document.getElementById("order-detail-overlay").style.display = "flex";
  } catch (e) { await rohuAlert("Error cargando pedido", "error"); }
}

// ── Actions ──────────────────────────────────────────────────────
async function confirmOrder(id) {
  try {
    const r = await (await fetch(`${OAPI}/${id}/confirm`, { method: "POST", headers: authH() })).json();
    if (r.success) { document.getElementById("order-detail-overlay").style.display = "none"; loadActiveOrders(); loadStats(); await rohuAlert("Pedido confirmado y enviado a preparacion", "success"); }
    else await rohuAlert(r.error?.message || "Error", "error");
  } catch (e) { await rohuAlert("Error de conexion", "error"); }
}

async function changeStatus(id, status) {
  try {
    const r = await (await fetch(`${OAPI}/${id}/status`, { method: "POST", headers: { ...authH(), "Content-Type": "application/json" }, body: JSON.stringify({ status }) })).json();
    if (r.success) { document.getElementById("order-detail-overlay").style.display = "none"; loadActiveOrders(); loadStats(); }
    else await rohuAlert(r.error?.message || "Error", "error");
  } catch (e) { await rohuAlert("Error", "error"); }
}

async function cancelOrder(id) {
  const reason = await rohuPrompt("Razon de cancelacion:", "Ej: Cliente cambio de opinion");
  if (!reason) return;
  try {
    const r = await (await fetch(`${OAPI}/${id}/cancel`, { method: "POST", headers: { ...authH(), "Content-Type": "application/json" }, body: JSON.stringify({ reason }) })).json();
    if (r.success) { document.getElementById("order-detail-overlay").style.display = "none"; loadActiveOrders(); loadStats(); await rohuAlert("Pedido cancelado", "warning"); }
    else await rohuAlert(r.error?.message || "Error", "error");
  } catch (e) { await rohuAlert("Error", "error"); }
}

async function showClosePopup(id, total) {
  const COP = n => "$" + Math.round(n).toLocaleString("es-CO");
  const ok = await rohuConfirm(
    `Cerrar pedido y cobrar <strong>${COP(total)}</strong>?<br><br><span style="font-size:12px;color:#64748B;">Esto creara la venta, descontara inventario y generara los asientos contables.</span>`,
    "Cobrar", "info"
  );
  if (!ok) return;

  try {
    const r = await (await fetch(`${OAPI}/${id}/close`, {
      method: "POST",
      headers: { ...authH(), "Content-Type": "application/json" },
      body: JSON.stringify({ payment_method: "cash", idempotency_key: crypto.randomUUID(), received_amount: total }),
    })).json();
    if (r.success) {
      document.getElementById("order-detail-overlay").style.display = "none";
      loadActiveOrders(); loadStats();
      await rohuAlert(`Pedido cerrado. Venta <strong>${r.data.sale?.invoice_number || ""}</strong> creada.`, "success");
    } else await rohuAlert(r.error?.message || "Error al cerrar", "error");
  } catch (e) { await rohuAlert("Error de conexion", "error"); }
}
