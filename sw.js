/* TraderWatch landing — service worker (tw-landing-v1).
 * Landing page self-contained (inline CSS/JS). Precache shell sahaja;
 * navigasi network-first fallback index.html; /api/* dan /member/* diurus
 * oleh service worker masing-masing (network sahaja di sini).
 */
const VERSION = 'tw-landing-v14';
const SHELL_CACHE = VERSION + '-shell';
const SHELL_ASSETS = [
  './',
  './index.html',
  './login.html',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/icon-180.png',
  './icons/apple-touch-icon.png'
];
const SHELL_PATHS = ['/index.html', '/login.html', '/manifest.webmanifest', '/icons/'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL_ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isShell(url) {
  return url.origin === self.location.origin &&
    (SHELL_PATHS.some((p) => url.pathname === p || url.pathname.startsWith(p)) || url.pathname === '/');
}

async function navFallback(request) {
  const url = new URL(request.url);
  const isHome = url.origin === self.location.origin && (url.pathname === '/' || url.pathname === '/index.html');
  const isLogin = url.origin === self.location.origin && url.pathname === '/login.html';
  /* Stale-while-revalidate untuk index.html & login.html sahaja supaya tukar halaman PWA serta-merta (0ms tunggu rangkaian) */
  if (isHome || isLogin) {
    const cacheKey = isLogin ? './login.html' : './index.html';
    const c = await caches.open(SHELL_CACHE);
    const cached = await c.match(cacheKey);
    const fresh = fetch(request).then((res) => {
      if (res && res.ok) c.put(cacheKey, res.clone());
      return res;
    }).catch(() => null);
    if (cached) return cached;
    const net = await fresh;
    if (net) return net;
    return new Response('Offline — halaman tidak dijumpai dalam cache.', { status: 503 });
  }
  try {
    return await fetch(request);
  } catch (err) {
    const c = await caches.open(SHELL_CACHE);
    return (await c.match('./index.html')) || (await c.match('./')) ||
      new Response('Offline — halaman tidak dijumpai dalam cache.', { status: 503 });
  }
}

self.addEventListener('fetch', (e) => {
  const { request } = e;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (request.mode === 'navigate') { e.respondWith(navFallback(request)); return; }
  if (url.origin !== self.location.origin) return;           // CDN/API luar: network
  if (url.pathname.startsWith('/api/')) return;              // API: network sahaja
  if (url.pathname.startsWith('/member/')) return;           // app member: SW sendiri
  if (isShell(url)) {
    e.respondWith(
      caches.open(SHELL_CACHE).then(async (c) => {
        const hit = await c.match(request, { ignoreSearch: true });
        if (hit) return hit;
        const res = await fetch(request);
        if (res && res.ok) c.put(request, res.clone());
        return res;
      })
    );
  }
  // aset lain: pass-through network, jangan cache
});