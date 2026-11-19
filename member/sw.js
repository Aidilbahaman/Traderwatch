/* TraderWatch Member PWA — service worker
 * Strategi:
 *  - App shell (HTML/CSS/JS/ikon): precache, cache-first + background update
 *  - Navigasi: network-first, fallback ke shell offline
 *  - Data JSON (signal/status/bars): stale-while-revalidate (offline = data cache terakhir)
 *  - Pihak ketiga (CDN supabase, TradingView): network sahaja, JANGAN cache
 *  - Push: sedia untuk VAPID (payload JSON {title, body, url, tag})
 */
const VERSION = 'tw-member-v4';
const SHELL_CACHE = VERSION + '-shell';
const DATA_CACHE = VERSION + '-data';

const SHELL_ASSETS = [
  './',
  './index.html',
  './app.css?v=20261120m4',
  './app.js?v=20261120m4',
  './chart.js?v=20261120m4',
  './auth.js?v=20261120m4',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/icon-180.png'
];

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

function isDataRequest(url) {
  return url.origin === self.location.origin && url.pathname.includes('/data/');
}

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
    // Hanya navigasi shell member disimpan sebagai fallback offline.
    // Halaman lain dalam scope (cth. elliot.html) JANGAN mencemari shell.
    const p = new URL(request.url).pathname;
    if (response && response.ok && (p === '/member/' || p === '/member/index.html')) {
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
  const cached = await cache.match(request);
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
  if (url.origin !== self.location.origin) return; // TradingView dll: network terus
  if (isDataRequest(url)) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }
  event.respondWith(cacheFirst(request));
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