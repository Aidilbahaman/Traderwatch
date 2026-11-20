/* TraderWatch AI Analyst PWA — service worker (app single-file)
 * Strategi:
 *  - App shell (index.html + manifest + ikon): precache, cache-first
 *  - Navigasi: network-first, fallback ke index.html bila offline
 *  - /api/* (analyze, bars): NETWORK SAHAJA — jangan cache data pasaran
 *  - Pihak ketiga: network terus
 */
const VERSION = 'tw-analyst-v1';
const SHELL_CACHE = VERSION + '-shell';

const SHELL_ASSETS = [
  './',
  './index.html',
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

async function networkFirstNavigation(request) {
  try {
    const response = await fetch(request);
    // Hanya shell analyst disimpan sebagai fallback offline.
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
  if (url.origin !== self.location.origin) return; // pihak ketiga: network terus
  if (url.pathname.startsWith('/api/')) return;    // analisis & bars: network sahaja
  event.respondWith(cacheFirst(request));
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});