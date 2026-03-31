/**
 * ROHU Contable — Service Worker v2
 * Strategies:
 *   - Static assets: Cache First
 *   - HTML pages: Network First (fall back to cache)
 *   - Product API: Stale While Revalidate (fast POS)
 *   - Other API: Network Only (offline handled by rohu-offline.js)
 *   - Offline POS: outbox queue in IndexedDB, sync on reconnect
 */

const CACHE_VERSION = '6';
const CACHE_NAME = `rohu-v${CACHE_VERSION}`;

const STATIC_ASSETS = [
  '/app/login',
  '/app/pos',
  '/app/dashboard',
  '/static/css/rohu.css',
  '/static/js/rohu-modal.js',
  '/static/js/rohu-offline.js',
  '/static/js/rohu-help.js',
  '/static/js/chart.min.js',
  '/static/img/logo-rohu.svg',
  '/static/img/icon-rohu.svg',
  '/static/manifest.json',
];

// ── Install ─────────────────────────────────────────────────────

self.addEventListener('install', event => {
  // Delete ALL old caches before installing new one
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.map(k => caches.delete(k)))
    ).then(() =>
      caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    )
  );
  self.skipWaiting();
});

// ── Activate ────────────────────────────────────────────────────

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch ───────────────────────────────────────────────────────

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API calls
  if (url.pathname.startsWith('/api/')) {
    // Respect cache:no-store from client (used after sales/adjustments for fresh data)
    if (event.request.cache === 'no-store') {
      event.respondWith(networkOnly(event.request));
      return;
    }
    // Product lookups: stale-while-revalidate for fast POS (only when not forced fresh)
    if (url.pathname.includes('/inventory/products') || url.pathname.includes('/products/scan')) {
      if (event.request.method === 'GET') {
        event.respondWith(staleWhileRevalidate(event.request));
        return;
      }
    }
    event.respondWith(networkOnly(event.request));
    return;
  }

  // Static assets: cache first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // HTML pages: network first, fallback to cache
  event.respondWith(networkFirst(event.request));
});

// ── Strategies ──────────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    return cached || new Response('Offline — sin conexión', {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }
}

async function networkOnly(request) {
  try {
    return await fetch(request);
  } catch (e) {
    return new Response(JSON.stringify({
      success: false,
      error: { code: 'OFFLINE', message: 'Sin conexión' }
    }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request).then(response => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);

  return cached || await fetchPromise || new Response(JSON.stringify({
    success: false, error: { code: 'OFFLINE', message: 'Sin conexión' }
  }), { status: 503, headers: { 'Content-Type': 'application/json' } });
}

// ── Background Sync ─────────────────────────────────────────────

self.addEventListener('sync', event => {
  if (event.tag === 'sync-outbox') {
    event.waitUntil(syncOutbox());
  }
});

async function syncOutbox() {
  const db = await openDB();
  const tx = db.transaction('outbox', 'readonly');
  const store = tx.objectStore('outbox');
  const items = await getAllFromStore(store);

  for (const item of items) {
    try {
      // Inject fresh token from the item's stored context
      const headers = { ...item.headers };
      // Token will be injected by rohu-offline.js sync, not stored in outbox

      const response = await fetch(item.url, {
        method: item.method,
        headers: headers,
        body: item.body,
      });

      if (response.ok) {
        const delTx = db.transaction('outbox', 'readwrite');
        delTx.objectStore('outbox').delete(item.id);
      }
    } catch (e) {
      // Continue trying other items (don't break on first failure)
      console.warn('SW sync failed for item', item.id, e);
      continue;
    }
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('rohu_offline', 1);
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
    request.onsuccess = (e) => resolve(e.target.result);
    request.onerror = (e) => reject(e.target.error);
  });
}

function getAllFromStore(store) {
  return new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

// ── Message handler ─────────────────────────────────────────────

self.addEventListener('message', event => {
  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
