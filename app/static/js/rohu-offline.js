/**
 * ROHU Offline Module v2
 * - Singleton IndexedDB connection
 * - Upsert product cache (no clear)
 * - Outbox queue with limit, fresh token injection, continue-on-error
 * - Offline checkout: queue sales for later sync
 * - Auto-sync on reconnect with retry tracking
 */

const ROHU_DB_NAME = 'rohu_offline';
const ROHU_DB_VERSION = 1;
const OUTBOX_MAX_ITEMS = 100;

// ── Singleton IndexedDB ─────────────────────────────────────────

let _dbInstance = null;

function rohuOpenDB() {
  if (_dbInstance) return Promise.resolve(_dbInstance);
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(ROHU_DB_NAME, ROHU_DB_VERSION);
    request.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('outbox')) {
        db.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true });
      }
      if (!db.objectStoreNames.contains('products')) {
        const ps = db.createObjectStore('products', { keyPath: 'id' });
        ps.createIndex('qr_code', 'qr_code', { unique: false });
        ps.createIndex('name', 'name', { unique: false });
      }
      if (!db.objectStoreNames.contains('cart')) {
        db.createObjectStore('cart', { keyPath: 'id', autoIncrement: true });
      }
      if (!db.objectStoreNames.contains('sync_meta')) {
        db.createObjectStore('sync_meta', { keyPath: 'key' });
      }
    };
    request.onsuccess = (e) => {
      _dbInstance = e.target.result;
      // Reset singleton if DB closes unexpectedly
      _dbInstance.onclose = () => { _dbInstance = null; };
      resolve(_dbInstance);
    };
    request.onerror = (e) => reject(e.target.error);
  });
}

// ── Products Cache (upsert, no clear) ───────────────────────────

async function rohuCacheProducts(products) {
  const db = await rohuOpenDB();
  const tx = db.transaction('products', 'readwrite');
  const store = tx.objectStore('products');
  // Upsert each product without clearing existing cache
  for (const p of products) {
    store.put(p);
  }
  // Save sync timestamp
  const metaTx = db.transaction('sync_meta', 'readwrite');
  metaTx.objectStore('sync_meta').put({
    key: 'products_last_sync',
    value: new Date().toISOString(),
    count: products.length,
  });
}

async function rohuGetCachedProducts(query) {
  const db = await rohuOpenDB();
  const tx = db.transaction('products', 'readonly');
  const store = tx.objectStore('products');

  return new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => {
      let results = request.result;
      if (query) {
        const q = query.toLowerCase();
        results = results.filter(p =>
          p.name.toLowerCase().includes(q) ||
          (p.sku && p.sku.toLowerCase().includes(q)) ||
          (p.qr_code && p.qr_code.toLowerCase().includes(q)) ||
          (p.barcode && p.barcode.toLowerCase().includes(q))
        );
      }
      resolve(results);
    };
    request.onerror = () => reject(request.error);
  });
}

async function rohuGetProductByQR(qrCode) {
  const db = await rohuOpenDB();
  const tx = db.transaction('products', 'readonly');
  const store = tx.objectStore('products');
  const index = store.index('qr_code');

  return new Promise((resolve, reject) => {
    const request = index.get(qrCode);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

// ── Outbox Queue (with limit and no auth storage) ───────────────

async function rohuAddToOutbox(url, method, headers, body) {
  const db = await rohuOpenDB();

  // Check limit
  const countTx = db.transaction('outbox', 'readonly');
  const count = await new Promise(resolve => {
    const req = countTx.objectStore('outbox').count();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(0);
  });

  if (count >= OUTBOX_MAX_ITEMS) {
    throw new Error(`Cola offline llena (${OUTBOX_MAX_ITEMS} max). Reconecte para sincronizar.`);
  }

  const tx = db.transaction('outbox', 'readwrite');
  const store = tx.objectStore('outbox');
  store.add({
    url,
    method,
    // EXCLUDE Authorization header — token injected fresh at sync time
    headers: Object.fromEntries(
      Object.entries(headers || {}).filter(([k]) => k.toLowerCase() !== 'authorization')
    ),
    body,
    created_at: new Date().toISOString(),
    status: 'pending',
    retry_count: 0,
  });
}

async function rohuGetOutboxCount() {
  try {
    const db = await rohuOpenDB();
    const tx = db.transaction('outbox', 'readonly');
    const store = tx.objectStore('outbox');
    return new Promise((resolve) => {
      const request = store.count();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(0);
    });
  } catch (e) {
    return 0;
  }
}

async function rohuSyncOutbox() {
  const db = await rohuOpenDB();
  const tx = db.transaction('outbox', 'readonly');
  const store = tx.objectStore('outbox');

  const items = await new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  // Get fresh token for all requests
  const freshToken = localStorage.getItem('access_token');
  let synced = 0;
  let failed = 0;

  for (const item of items) {
    try {
      // Inject fresh Authorization header
      const headers = {
        ...item.headers,
        'Authorization': `Bearer ${freshToken}`,
        'Content-Type': 'application/json',
      };

      const response = await fetch(item.url, {
        method: item.method,
        headers: headers,
        body: item.body,
      });

      if (response.ok) {
        const delTx = db.transaction('outbox', 'readwrite');
        delTx.objectStore('outbox').delete(item.id);
        synced++;
      } else if (response.status === 409) {
        // Conflict (duplicate) — remove from queue, already processed
        const delTx = db.transaction('outbox', 'readwrite');
        delTx.objectStore('outbox').delete(item.id);
        synced++;
      } else {
        // Server error — increment retry count
        const updTx = db.transaction('outbox', 'readwrite');
        const updStore = updTx.objectStore('outbox');
        item.retry_count = (item.retry_count || 0) + 1;
        if (item.retry_count >= 3) {
          item.status = 'failed';
        }
        updStore.put(item);
        failed++;
      }
    } catch (e) {
      // Network error — increment retry but continue with next
      console.warn('Sync failed for item', item.id, e.message);
      try {
        const updTx = db.transaction('outbox', 'readwrite');
        item.retry_count = (item.retry_count || 0) + 1;
        updTx.objectStore('outbox').put(item);
      } catch (ue) { /* ignore */ }
      failed++;
      continue; // DON'T break — try next item
    }
  }
  return { synced, failed, remaining: items.length - synced };
}

// ── Offline-aware Fetch ─────────────────────────────────────────

async function rohuFetch(url, options = {}) {
  if (navigator.onLine) {
    return fetch(url, options);
  }

  // If it's a checkout (POST to /pos/checkout), queue it
  if (options.method === 'POST' && url.includes('/pos/checkout')) {
    await rohuAddToOutbox(url, options.method, options.headers || {}, options.body);
    return new Response(JSON.stringify({
      success: true,
      data: { offline: true, message: 'Venta guardada. Se sincronizará al reconectar.' },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }

  // For GET product queries, try IndexedDB
  if (url.includes('/inventory/products')) {
    const urlObj = new URL(url, window.location.origin);
    const query = urlObj.searchParams.get('q') || '';
    const products = await rohuGetCachedProducts(query);
    return new Response(JSON.stringify({
      success: true, data: products,
      pagination: { page: 1, per_page: 500, total: products.length },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }

  if (url.includes('/products/scan')) {
    const urlObj = new URL(url, window.location.origin);
    const qr = urlObj.searchParams.get('qr') || '';
    const product = await rohuGetProductByQR(qr);
    if (product) {
      return new Response(JSON.stringify({ success: true, data: product }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
  }

  // Default: fail with offline message
  return new Response(JSON.stringify({
    success: false, error: { code: 'OFFLINE', message: 'Sin conexión' }
  }), { status: 503, headers: { 'Content-Type': 'application/json' } });
}

// ── Auto-sync on reconnect ──────────────────────────────────────

window.addEventListener('online', async () => {
  const count = await rohuGetOutboxCount();
  if (count > 0) {
    if (typeof rohuAlert === 'function') {
      rohuAlert(`Sincronizando ${count} operación(es)...`, 'info');
    }
    const result = await rohuSyncOutbox();
    if (result.synced > 0 && typeof rohuAlert === 'function') {
      rohuAlert(`${result.synced} operación(es) sincronizada(s) exitosamente`, 'success');
    }
    if (result.failed > 0 && typeof rohuAlert === 'function') {
      rohuAlert(`${result.failed} operación(es) fallaron. Se reintentarán.`, 'warning');
    }
    rohuUpdateOutboxBadge();
  }
});

// ── Product cache refresh (call after login or periodically) ────

async function rohuRefreshProductCache() {
  if (!navigator.onLine) return;
  try {
    const token = localStorage.getItem('access_token');
    const resp = await fetch('/api/v1/inventory/products?per_page=1000', {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (resp.ok) {
      const { data } = await resp.json();
      await rohuCacheProducts(data);
      console.log(`ROHU offline: ${data.length} products cached`);
    }
  } catch (e) {
    // Silently fail — will retry next page load
  }
}

// ── Pending outbox badge ────────────────────────────────────────

async function rohuUpdateOutboxBadge() {
  const count = await rohuGetOutboxCount();
  const el = document.getElementById('outbox-badge');
  if (el) {
    if (count > 0) {
      el.textContent = `${count} pendiente(s)`;
      el.style.display = 'inline';
    } else {
      el.textContent = '';
      el.style.display = 'none';
    }
  }
}

// Expose globally
window.rohuFetch = rohuFetch;
window.rohuOpenDB = rohuOpenDB;
window.rohuCacheProducts = rohuCacheProducts;
window.rohuGetCachedProducts = rohuGetCachedProducts;
window.rohuGetProductByQR = rohuGetProductByQR;
window.rohuAddToOutbox = rohuAddToOutbox;
window.rohuRefreshProductCache = rohuRefreshProductCache;
window.rohuGetOutboxCount = rohuGetOutboxCount;
window.rohuSyncOutbox = rohuSyncOutbox;
window.rohuUpdateOutboxBadge = rohuUpdateOutboxBadge;
