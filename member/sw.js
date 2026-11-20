/* TraderWatch AI Analyst — service worker app ahli 5-area (member/).
 * Strategi:
 *  - App shell (index.html + manifest + ikon): precache, cache-first
 *  - Navigasi: network-first, fallback ke index.html bila offline
 *  - /api/* dan /auth/*: NETWORK SAHAJA — jangan cache data pasaran/user
 *  - Data user (Supabase REST, chat, profil): tidak dicache sama sekali
 */
const VERSION = 'tw-member-full-v5';
const SHELL_CACHE = VERSION + '-shell';

const SHELL_ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/icon-180.png',
  './icons/apple-touch-icon.png'
];

const SHELL_PATHS = new Set([
  '/member/', '/member/index.html', '/member/manifest.webmanifest',
  '/member/icons/icon-192.png', '/member/icons/icon-512.png',
  '/member/icons/icon-maskable-512.png', '/member/icons/icon-180.png',
  '/member/icons/apple-touch-icon.png'
]);

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
    // Hanya shell app disimpan sebagai fallback offline.
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

async function cacheFirstShell(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return; // POST analyze/chat: network terus
  const url = new URL(request.url);

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request));
    return;
  }
  if (url.origin !== self.location.origin) return; // Supabase & pihak ketiga: network terus
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) return; // jangan cache
  if (SHELL_PATHS.has(url.pathname)) {
    event.respondWith(cacheFirstShell(request));
    return;
  }
  // Laluan lain (data feed dll): network sahaja, tiada cache data user.
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
