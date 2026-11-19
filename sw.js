/* TraderWatch ROOT PWA — service worker (scope SELURUH SITE)
 * Strategi selamat untuk root (mengawal semua halaman termasuk legacy):
 *  - App shell (index/pwa.css/pwa.js/chart.js/manifest/ikon): precache, cache-first
 *  - Navigasi: network-first, fallback ke shell offline (banner offline dalam app)
 *  - Data JSON HANYA /data/ (root): stale-while-revalidate.
 *    /pwa-app/data/ dan /member/data/ diurus oleh SW scope masing-masing.
 *  - SEMUA aset same-origin LAIN (common.js, members-tools.js, config.js,
 *    app.css legacy, education.js, imej assets/ dll): NETWORK PASS-THROUGH,
 *    JANGAN cache — halaman legacy tidak boleh dapat aset basi.
 *  - Pihak ketiga (TradingView, supabase CDN): network sahaja, jangan cache.
 *  - Push: sedia untuk VAPID (payload JSON {title, body, url, tag})
 */
const VERSION = 'tw-root-v3';
const SHELL_CACHE = VERSION + '-shell';
const DATA_CACHE = VERSION + '-data';

const SHELL_ASSETS = [
  './',
  './index.html',
  './pwa.css?v=20261120r3',
  './pwa.js?v=20261120r3',
  './chart.js?v=20261120r3',
  './app.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/icon-180.png'
];

/* Whitelist shell: padanan pathname (abaikan query cache-bust). */
const SHELL_PATHS = new Set([
  '/',
  '/index.html',
  '/pwa.css',
  '/pwa.js',
  '/chart.js',
  '/app.webmanifest'
]);

function isShellAsset(url) {
  return SHELL_PATHS.has(url.pathname) || url.pathname.startsWith('/icons/');
}

function isDataRequest(url) {
  return url.origin === self.location.origin && url.pathname.startsWith('/data/');
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

async function staleWhileRevalidate(request) {
  const cache = await caches.open(DATA_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return cached || (await network) || new Response('null', {
    status: 200,
    headers: { 'Content-Type': 'application/json' }
  });
}

async function networkFirstNavigation(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok && new URL(request.url).pathname === '/') {
      const cache = await caches.open(SHELL_CACHE);
      cache.put('./index.html', response.clone());
    }
    return response;
  } catch (err) {
    const cache = await caches.open(SHELL_CACHE);
    return (await cache.match('./index.html')) || (await cache.match('./')) ||
      new Response('Offline — app shell tidak dijumpai dalam cache.', { status: 503 });
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request, { ignoreSearch: true });
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request));
    return;
  }
  if (url.origin !== self.location.origin) return; // TradingView/CDN: network terus
  if (isDataRequest(url)) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }
  if (isShellAsset(url)) {
    event.respondWith(cacheFirst(request));
    return;
  }
  // Semua aset same-origin lain: pass-through network, JANGAN cache.
  event.respondWith(fetch(request));
});

/* ---- Push notifications (sedia untuk backend VAPID) ---- */
self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (e) { /* teks biasa */ }
  const title = payload.title || 'TraderWatch';
  const options = {
    body: payload.body || 'Signal baru diterbitkan. Buka app untuk semak.',
    tag: payload.tag || 'tw-signal',
    icon: './icons/icon-192.png',
    badge: './icons/icon-192.png',
    data: { url: payload.url || './index.html#/home' },
    requireInteraction: false
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || './index.html#/home';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});