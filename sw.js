/* ==========================================================================
   Service Worker - Alerta Campus (PWA de incidencias)
   Ciclo de vida : install -> waiting -> activate  (la actualización la decide el usuario)
   Caché         : precaché del "app shell" + estrategia red-primero con respaldo en caché
   Notificaciones: evento push (servidor) y notificationclick (locales y push)
   ========================================================================== */

// Subir VERSION cada vez que cambie cualquier archivo del App Shell (provoca la actualización).
const VERSION = 'v6';
const CACHE   = `incidencias-${VERSION}`;
const NET_TIMEOUT_MS = 4000;          // si la red tarda más (lie-fi), se usa la caché

// App Shell: todo lo necesario para abrir la interfaz sin conexión.
const ASSETS = [
  './', './index.html', './manifest.json',
  './icon.svg', './icon-maskable.svg',
  './icon-192.png', './icon-512.png', './icon-maskable-512.png',
  './imag1.png', './image2.png', './image3.png', './image4.png', './image5.png', './image6.png'
];

// ---- INSTALL: se precachea el App Shell. Si un archivo falla, la instalación falla
//      y el navegador conserva el SW anterior (no se rompe la app).
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  // NO se llama skipWaiting() aquí: el nuevo SW queda en "waiting" hasta que el usuario
  // acepta la actualización desde el aviso de la app (mensaje SKIP_WAITING).
});

// ---- ACTIVATE: se eliminan las cachés de versiones anteriores y se toma control de las pestañas.
self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k.startsWith('incidencias-') && k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

// ---- Mensajes desde la página
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
  if (e.data && e.data.type === 'GET_VERSION' && e.source) e.source.postMessage({ type: 'VERSION', version: VERSION });
});

// ---- FETCH: red primero (siempre la versión más reciente) con tiempo límite; si falla -> caché.
self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  // La API y lo que no sea GET del mismo origen NO se interceptan: la app gestiona esos errores
  // (datos en IndexedDB + cola de pendientes).
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  e.respondWith(networkFirst(req));
});

async function networkFirst(req) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), NET_TIMEOUT_MS);
  try {
    const res = await fetch(req, { signal: ctrl.signal });
    clearTimeout(timer);
    // Solo se guardan respuestas correctas (antes se guardaban también los 404).
    if (res.ok && res.type === 'basic') {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
    }
    return res;
  } catch (_) {
    clearTimeout(timer);
    const hit = await caches.match(req, { ignoreSearch: true });
    if (hit) return hit;
    // Navegación a una URL no cacheada (p. ej. un acceso directo con #hash): se abre la app.
    if (req.mode === 'navigate') return (await caches.match('./index.html')) || Response.error();
    return Response.error();
  }
}

// ---- PUSH: notificación enviada por el servidor (funciona con la app cerrada).
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data && e.data.text() }; }
  const title = d.title || 'Alerta Campus';
  e.waitUntil(self.registration.showNotification(title, {
    body : d.body || 'Hay novedades en las incidencias.',
    icon : './icon-192.png',
    badge: './icon-192.png',
    tag  : d.tag || 'push',
    lang : 'es',
    data : { view: d.view || 'list' }
  }));
});

// ---- Clic en una notificación (local o push): enfoca la app y abre la vista indicada.
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const view = (e.notification.data && e.notification.data.view) || 'list';
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) {
      if (new URL(w.url).origin === location.origin) {
        await w.focus();
        w.postMessage({ type: 'NAVIGATE', view });
        return;
      }
    }
    await self.clients.openWindow(`./index.html#${view}`);
  })());
});
