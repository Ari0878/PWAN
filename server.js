// Servidor mínimo: sirve la PWA y una API REST con CRUD + servicio de notificaciones push.
// Uso: node server.js        (el push real requiere:  npm install   -> instala "web-push")
const http = require('http'), fs = require('fs'), path = require('path');

// ---------------------------------------------------------------- Base de datos (JSON)
const DB = 'db.json';
let data = fs.existsSync(DB) ? JSON.parse(fs.readFileSync(DB) || '[]') : [];
const save = () => fs.writeFileSync(DB, JSON.stringify(data, null, 2));

// ---------------------------------------------------------------- Push (opcional)
// Si el paquete "web-push" no está instalado, la app funciona igual y /api/push/* responde 501.
let webpush = null;
try { webpush = require('web-push'); } catch (_) { /* push desactivado */ }
const SUBS_FILE = 'subs.json', VAPID_FILE = 'vapid.json';
let vapid = null, subs = [];
if (webpush) {
  // Las claves VAPID identifican al servidor ante el servicio push del navegador.
  // En hosting con disco efímero conviene definirlas por variables de entorno.
  if (process.env.VAPID_PUBLIC_KEY && process.env.VAPID_PRIVATE_KEY) {
    vapid = { publicKey: process.env.VAPID_PUBLIC_KEY, privateKey: process.env.VAPID_PRIVATE_KEY };
  } else if (fs.existsSync(VAPID_FILE)) {
    vapid = JSON.parse(fs.readFileSync(VAPID_FILE));
  } else {
    vapid = webpush.generateVAPIDKeys();
    fs.writeFileSync(VAPID_FILE, JSON.stringify(vapid, null, 2));
    console.log('Claves VAPID generadas en', VAPID_FILE, '(no se suben a GitHub)');
  }
  webpush.setVapidDetails(process.env.VAPID_SUBJECT || 'mailto:equipo@example.com', vapid.publicKey, vapid.privateKey);
  subs = fs.existsSync(SUBS_FILE) ? JSON.parse(fs.readFileSync(SUBS_FILE) || '[]') : [];
}
const saveSubs = () => fs.writeFileSync(SUBS_FILE, JSON.stringify(subs, null, 2));

// Envía un mensaje a una suscripción (o a todas). Elimina las suscripciones caducadas (404/410).
async function pushTo(list, payload) {
  const msg = JSON.stringify(payload);
  let sent = 0;
  await Promise.all(list.map(async s => {
    try { await webpush.sendNotification(s, msg); sent++; }
    catch (err) {
      if (err.statusCode === 404 || err.statusCode === 410) { subs = subs.filter(x => x.endpoint !== s.endpoint); saveSubs(); }
      else console.warn('push falló:', err.statusCode || err.message);
    }
  }));
  return sent;
}

// ---------------------------------------------------------------- Utilidades HTTP
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };
const json = (res, code, obj) => { res.statusCode = code; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(obj)); };
const body = req => new Promise(ok => { let b = ''; req.on('data', c => { b += c; if (b.length > 1e6) req.destroy(); });
  req.on('end', () => { try { ok(JSON.parse(b || '{}')); } catch (_) { ok(null); } }); });

// Solo estos archivos se sirven. Así NO quedan expuestos db.json, vapid.json, subs.json, server.js ni .git
const PUBLIC = /^\/(index\.html|sw\.js|manifest\.json|[\w-]+\.(svg|png))$/;

// Ubicación opcional {lat, lng, precision, ts}: se valida y se limpia
function cleanGeo(g) {
  if (!g || typeof g !== 'object') return undefined;
  const lat = Number(g.lat), lng = Number(g.lng);
  if (!isFinite(lat) || !isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return undefined;
  return { lat, lng, precision: isFinite(Number(g.precision)) ? Number(g.precision) : null, ts: g.ts || null };
}

// Crear o actualizar (idempotente): el id lo genera el cliente, así un reintento no duplica
function upsert(it) {
  const k = data.findIndex(x => x.id === it.id);
  const clean = { id: it.id, titulo: it.titulo, prioridad: it.prioridad, descripcion: it.descripcion || '',
    fecha: it.fecha, updated: it.updated || it.fecha, synced: true };
  const geo = cleanGeo(it.ubicacion); if (geo) clean.ubicacion = geo;
  if (k < 0) { data.push(clean); return 'created'; }
  if ((clean.updated || '') >= (data[k].updated || '')) { data[k] = clean; return 'updated'; }
  return 'ignored';                       // llegó una versión más vieja: se conserva la del servidor
}

http.createServer(async (req, res) => {
  const url = req.url.split('?')[0];

  // ---- API de incidencias (CRUD)
  const m = url.match(/^\/api\/incidencias(?:\/([^/]+))?$/);
  if (m) {
    const id = m[1] && decodeURIComponent(m[1]);
    if (req.method === 'GET' && !id) return json(res, 200, data);                                    // READ (lista)
    if (req.method === 'GET' && id) { const x = data.find(d => d.id === id); return x ? json(res, 200, x) : json(res, 404, { ok: false }); }
    if (req.method === 'POST' && !id) {                                                              // CREATE
      const it = await body(req); if (!it || !it.id || !it.titulo) return json(res, 400, { ok: false, error: 'Datos inválidos' });
      const r = upsert(it); save();
      // Servicio de envío: una incidencia ALTA nueva avisa por push a todos los suscritos
      if (r === 'created' && it.prioridad === 'Alta' && webpush && subs.length)
        pushTo(subs, { title: 'Incidencia de prioridad alta', body: it.titulo, tag: 'alta-' + it.id, view: 'list' });
      return json(res, r === 'created' ? 201 : 200, { ok: true, id: it.id, result: r });
    }
    if (req.method === 'PUT' && id) {                                                                // UPDATE
      const it = await body(req); if (!it || !it.titulo) return json(res, 400, { ok: false, error: 'Datos inválidos' });
      const r = upsert({ ...it, id }); save(); return json(res, 200, { ok: true, id, result: r });
    }
    if (req.method === 'DELETE' && id) {                                                             // DELETE (idempotente)
      const n = data.length; data = data.filter(x => x.id !== id); if (data.length !== n) save();
      return json(res, 200, { ok: true, id });
    }
    return json(res, 405, { ok: false });
  }

  // ---- API de notificaciones push
  if (url.startsWith('/api/push/')) {
    if (!webpush) return json(res, 501, { ok: false, error: 'Push no disponible: ejecuta "npm install" en el servidor' });
    if (req.method === 'GET' && url === '/api/push/key') return json(res, 200, { key: vapid.publicKey });
    if (req.method === 'POST' && url === '/api/push/subscribe') {
      const s = await body(req);
      if (!s || !s.endpoint || !s.keys) return json(res, 400, { ok: false, error: 'Suscripción inválida' });
      if (!subs.some(x => x.endpoint === s.endpoint)) { subs.push(s); saveSubs(); }
      return json(res, 201, { ok: true, total: subs.length });
    }
    if (req.method === 'POST' && url === '/api/push/unsubscribe') {
      const s = await body(req); subs = subs.filter(x => !s || x.endpoint !== s.endpoint); saveSubs();
      return json(res, 200, { ok: true });
    }
    // Prueba: solo se envía a la suscripción de quien la solicita (no hay difusión abierta)
    if (req.method === 'POST' && url === '/api/push/test') {
      const s = await body(req); const mine = s && subs.find(x => x.endpoint === s.endpoint);
      if (!mine) return json(res, 404, { ok: false, error: 'Suscripción no registrada' });
      const n = await pushTo([mine], { title: 'Notificación push de prueba', body: 'El servidor de envío funciona correctamente.', tag: 'push-test', view: 'home' });
      return json(res, n ? 200 : 502, { ok: !!n });
    }
    return json(res, 405, { ok: false });
  }

  // ---- Archivos estáticos (lista blanca)
  const rel = url === '/' ? '/index.html' : url;
  if (!PUBLIC.test(rel)) { res.statusCode = 404; return res.end('404'); }
  fs.readFile(path.join(__dirname, rel), (e, c) => {
    if (e) { res.statusCode = 404; return res.end('404'); }
    res.setHeader('Content-Type', types[path.extname(rel)] || 'application/octet-stream');
    // sw.js y la página no deben quedar en la caché HTTP, o el navegador tardaría en ver las actualizaciones
    if (rel === '/sw.js' || rel === '/index.html' || rel === '/manifest.json') res.setHeader('Cache-Control', 'no-cache');
    res.end(c);
  });
}).listen(process.env.PORT || 3000, () => console.log('http://localhost:' + (process.env.PORT || 3000), webpush ? '(push activo)' : '(push desactivado: falta npm install)'));
