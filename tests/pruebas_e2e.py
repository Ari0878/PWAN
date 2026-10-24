"""
Pruebas automatizadas de la PWA (Playwright + Chromium).
Uso:  node server.js   (en otra terminal)   y luego:   python3 tests/pruebas_e2e.py
Genera docs/resultados_pruebas.json y las capturas en docs/capturas/.
Requisitos: pip install playwright && playwright install chromium
"""
import json, os, re, sys, time, urllib.request
from playwright.sync_api import sync_playwright

BASE  = os.environ.get('BASE', 'http://localhost:3000')
ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, 'docs', 'capturas')
SWJS  = os.path.join(ROOT, 'sw.js')
GEO   = {'latitude': 19.2833, 'longitude': -99.5167, 'accuracy': 25}
os.makedirs(SHOTS, exist_ok=True)
R = []   # resultados

def api(path, method='GET', body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r: return r.status, json.loads(r.read() or 'null')
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or 'null')
        except Exception: return e.code, None

def rec(id_, nombre, esperado, obtenido, ok):
    R.append({'id': id_, 'prueba': nombre, 'esperado': esperado, 'obtenido': obtenido, 'estado': 'APROBADO' if ok else 'FALLIDO'})
    print(('PASS' if ok else 'FAIL'), id_, '-', nombre, '|', obtenido)

def ready(page):
    page.wait_for_selector('#splash.hide', state='attached', timeout=8000)
    page.wait_for_timeout(700)

def shot(page, name, full=False):
    page.wait_for_timeout(450)                      # deja terminar las transiciones CSS
    if full:                                        # en capturas largas la barra fija taparía el contenido
        page.add_style_tag(content='nav,#toast{visibility:hidden!important}')
    page.screenshot(path=os.path.join(SHOTS, name), full_page=full)
    if full:
        page.evaluate("document.querySelectorAll('style:last-of-type').forEach(s => s.textContent.includes('visibility:hidden!important') && s.remove())")

def toast_text(page):
    page.wait_for_selector('#toast.on', timeout=4000)
    return page.text_content('#tmsg')

def go(page, v):
    page.click(f'nav button[data-v={v}]'); page.wait_for_timeout(350)

def notifs(page, tag=None):
    return page.evaluate("""async t => { const r = await navigator.serviceWorker.getRegistration();
        const n = await r.getNotifications(t ? {tag:t} : {}); return n.map(x => ({title:x.title, body:x.body, tag:x.tag, view:(x.data||{}).view})); }""", tag)

with sync_playwright() as p:
    # Se usa Chrome completo en modo headless=new (el "headless shell" reporta mal Notification.permission)
    FULL = os.environ.get('CHROME', '/opt/pw-browsers/chromium-1194/chrome-linux/chrome')
    br = p.chromium.launch(executable_path=FULL, args=['--headless=new']) if os.path.exists(FULL) else p.chromium.launch(headless=True)
    errors = []

    # =============== Contexto A: permisos concedidos (notificaciones + geolocalización)
    ctx = br.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                         locale='es-MX', geolocation=GEO, permissions=['notifications', 'geolocation'])
    page = ctx.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(BASE + '/'); ready(page)

    # ---- P1. Registro del Service Worker
    info = page.evaluate("""async () => { const r = await navigator.serviceWorker.ready;
        return {scope: r.scope, state: r.active && r.active.state, script: r.active && r.active.scriptURL}; }""")
    page.wait_for_function("document.getElementById('swstate').textContent.includes('Service Worker activo')", timeout=6000)
    sw_txt = page.text_content('#swstate')
    rec('P1', 'La aplicación registra correctamente el Service Worker',
        'Registro con scope raíz, estado "activated" y estado visible en la interfaz',
        f"scope={info['scope']} · estado={info['state']} · UI: «{sw_txt}»",
        info['state'] == 'activated' and info['scope'].rstrip('/') == BASE and 'activo' in sw_txt)
    shot(page, '01-inicio-service-worker-y-notificaciones.png', full=True)

    # Recarga para quedar controlados por el SW
    page.reload(); ready(page)
    ctrl = page.evaluate("!!navigator.serviceWorker.controller")
    keys = page.evaluate("caches.keys().then(k => Promise.all(k.map(async n => [n, (await (await caches.open(n)).keys()).map(r => new URL(r.url).pathname)])))")
    cache_name, cache_files = keys[0][0], keys[0][1]
    esperados = ['/', '/index.html', '/manifest.json', '/icon.svg', '/icon-192.png', '/imag1.png', '/image6.png']
    faltan = [f for f in esperados if f not in cache_files]
    rec('P2a', 'Precaché del App Shell al instalar el Service Worker',
        'La caché incidencias-v6 contiene HTML, manifest, iconos e imágenes',
        f'caché={cache_name} · {len(cache_files)} recursos · faltan={faltan or "ninguno"} · página controlada={ctrl}',
        cache_name == 'incidencias-v6' and not faltan and ctrl)

    # ---- P2b. Funcionamiento sin conexión
    ctx.set_offline(True)
    page.reload(); ready(page)
    st = page.text_content('#stt'); title = page.title()
    imgs = page.evaluate("[...document.querySelectorAll('.cr img')].map(i => i.complete && i.naturalWidth > 0)")
    visible = page.is_visible('#v-home') and page.is_visible('nav')
    rec('P2b', 'Los recursos esenciales se cargan después de activar el modo sin conexión',
        'Con la red cortada la interfaz abre completa (HTML, estilos, iconos, imágenes) e indica "Sin conexión"',
        f'título="{title}" · estado="{st}" · interfaz visible={visible} · imágenes cargadas={sum(imgs)}/{len(imgs)}',
        visible and st == 'Sin conexión' and all(imgs) and len(imgs) >= 5)
    shot(page, '02-sin-conexion-interfaz-desde-cache.png')

    # ---- Registrar una incidencia SIN conexión, con ubicación (característica del dispositivo)
    go(page, 'new')
    page.click('#gbtn')
    page.wait_for_function("document.getElementById('gstate').textContent.includes('adjuntada')", timeout=8000)
    gmsg = page.text_content('#gstate')
    page.fill('#t', 'Fuga de agua en el pasillo B'); page.fill('#d', 'Edificio B, planta baja, junto a los sanitarios')
    page.click('label[for=p2]')
    shot(page, '03-geolocalizacion-ubicacion-adjuntada.png', full=True)
    page.click('#save'); msg = toast_text(page)
    page.wait_for_timeout(400)
    go(page, 'list')
    stored = page.evaluate("""() => new Promise(ok => { const r = indexedDB.open('incidenciasDB'); r.onsuccess = () => {
        const q = r.result.transaction('items').objectStore('items').getAll(); q.onsuccess = () => ok(q.result); }; })""")
    mine = [i for i in stored if i['titulo'] == 'Fuga de agua en el pasillo B'][0]
    ub = mine.get('ubicacion') or {}
    rec('P5a', 'La característica del dispositivo (geolocalización) funciona con el permiso autorizado',
        'Al pulsar «Usar mi ubicación» se obtienen latitud, longitud y precisión y se guardan con la incidencia',
        f'mensaje="{gmsg}" · guardado en IndexedDB: lat={ub.get("lat")}, lng={ub.get("lng")}, ±{ub.get("precision")} m',
        abs(ub.get('lat', 0) - GEO['latitude']) < 1e-4 and abs(ub.get('lng', 0) - GEO['longitude']) < 1e-4 and 'sin conexión' in msg.lower())
    shot(page, '04-historial-pendiente-con-ubicacion.png')

    # ---- P3. Avisos de funciones que requieren conexión
    maplink = page.text_content('#list a.mapl')
    page.click('#list a.mapl'); t_map = toast_text(page)
    page.wait_for_timeout(2800)
    go(page, 'home')
    page.click('#sync'); t_sync = toast_text(page)
    shot(page, '05-aviso-funcion-requiere-conexion.png')
    page.wait_for_timeout(2800)
    page.click('#pbtn'); p_txt = page.text_content('#pstate')
    rec('P3', 'La aplicación informa adecuadamente cuando una función necesita conexión',
        'Sin red: sincronizar, ver el mapa y activar push muestran un aviso claro (sin errores ni pantallas en blanco)',
        f'sincronizar → «{t_sync}» · mapa → «{t_map}» · push → «{p_txt}»',
        'requiere internet' in t_sync and 'requiere conexión' in t_map and 'requiere conexión' in p_txt)

    # ---- Reconexión: sincronización automática + notificación
    ctx.set_offline(False)
    page.wait_for_function("document.getElementById('pen').textContent === '0'", timeout=10000)
    page.wait_for_timeout(600)
    srv = api('/api/incidencias')[1]
    en_srv = [i for i in srv if i['titulo'] == 'Fuga de agua en el pasillo B']
    n_sync = notifs(page, 'sync')
    rec('P6', 'Las incidencias guardadas sin conexión se envían al reconectar (sin duplicados) con su ubicación',
        'Al volver la red: pendientes = 0, un solo registro en el servidor con ubicación, y aviso de sincronización completa',
        f'registros en servidor={len(en_srv)} · ubicación en servidor={en_srv[0].get("ubicacion") if en_srv else None} · notificación="{n_sync[0]["title"] if n_sync else None}"',
        len(en_srv) == 1 and bool(en_srv[0].get('ubicacion')) and len(n_sync) == 1)

    # ---- P4. Notificaciones locales con permiso concedido
    perm = page.evaluate("Notification.permission")
    page.reload(); ready(page)
    nstate = page.text_content('#nstate'); btn_dis = page.is_disabled('#nbtn')
    shot(page, '06-notificaciones-permiso-concedido.png')
    page.click('#ntest'); t_ok = toast_text(page); n_test = notifs(page, 'prueba')
    go(page, 'new'); page.fill('#t', 'Cortocircuito en laboratorio 3'); page.click('label[for=p3]')
    page.click('#save'); page.wait_for_timeout(900)
    n_alta = [n for n in notifs(page) if n['tag'].startswith('alta-')]
    rec('P4', 'La notificación se muestra después de conceder el permiso correspondiente',
        'Con permiso "granted": la prueba y la incidencia de prioridad ALTA generan una notificación del sistema',
        f'permiso={perm} · estado UI="{nstate[:40]}…" · botón desactivado={btn_dis} · prueba={n_test[0]["title"] if n_test else None} · alta={n_alta[0]["title"] + ": " + n_alta[0]["body"] if n_alta else None}',
        perm == 'granted' and len(n_test) == 1 and len(n_alta) == 1 and btn_dis)
    page.wait_for_timeout(2800)
    go(page, 'list'); shot(page, '07-historial-incidencia-alta-y-ubicacion.png')

    # ---- Acceso directo / destino de la notificación: #list
    page.goto(BASE + '/#list'); ready(page)
    rec('P4b', 'El destino de la notificación y los accesos directos abren la vista correcta',
        'Abrir /#list muestra el Historial', f'vista activa={page.evaluate("document.querySelector(\'.view.on\').id")}',
        page.evaluate("document.querySelector('.view.on').id") == 'v-list')

    # ---- Actualización del Service Worker (v6 -> v7)
    original = open(SWJS, encoding='utf-8').read()
    try:
        open(SWJS, 'w', encoding='utf-8').write(original.replace("VERSION = 'v6'", "VERSION = 'v7'"))
        page.goto(BASE + '/'); ready(page)
        page.evaluate("navigator.serviceWorker.getRegistration().then(r => r.update())")
        page.wait_for_selector('#upd.on', timeout=8000)
        antes = page.evaluate("caches.keys()")
        shot(page, '08-aviso-nueva-version.png')
        page.click('#updbtn')
        page.wait_for_function("navigator.serviceWorker.controller && caches.keys().then(k => k.join() === 'incidencias-v7') && true", timeout=1000) if False else None
        page.wait_for_timeout(2500); ready(page)
        despues = page.evaluate("caches.keys()")
        rec('P7', 'Actualización del Service Worker (install → waiting → activate)',
            'Un SW nuevo queda en espera, la app avisa, y al aceptar se activa, se borra la caché vieja y se recarga',
            f'cachés antes={antes} · después={despues}', 'incidencias-v6' in antes and despues == ['incidencias-v7'])
    finally:
        open(SWJS, 'w', encoding='utf-8').write(original)
    ctx.close()

    # =============== Contexto B: SIN permisos (comportamiento ante denegación)
    ctxB = br.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, locale='es-MX')
    pb = ctxB.new_page(); pb.goto(BASE + '/'); ready(pb)
    perm0 = pb.evaluate("Notification.permission")
    n0 = pb.text_content('#nstate')
    # El usuario pulsa «Bloquear» en el permiso de ubicación (se fija el estado "denied" para este origen)
    cdp = br.new_browser_cdp_session()
    ctx_id = [t for t in cdp.send('Target.getTargets')['targetInfos'] if t['type'] == 'page' and t['url'].startswith(BASE)][0]['browserContextId']
    cdp.send('Browser.setPermission', {'origin': BASE, 'permission': {'name': 'geolocation'}, 'setting': 'denied', 'browserContextId': ctx_id})
    go(pb, 'new'); pb.click('#gbtn'); pb.wait_for_timeout(1200)
    g0 = pb.text_content('#gstate'); cls = pb.get_attribute('#gstate', 'class')
    shot(pb, '09-permiso-ubicacion-denegado.png', full=True)
    pb.fill('#t', 'Incidencia sin ubicación'); pb.click('#save'); pb.wait_for_timeout(800)
    t_nogeo = 'guardada en el historial' if 'Incidencia sin ubicación' in pb.text_content('#list') else 'NO guardada'
    rec('P5b', 'Sin permiso de ubicación la app informa y permite continuar',
        'Mensaje de error comprensible y la incidencia puede guardarse sin ubicación',
        f'mensaje="{g0}" · guardado="{t_nogeo}"', 'err' in cls and ('denegado' in g0.lower() or 'bloqueado' in g0.lower()) and t_nogeo.startswith('guardada'))
    go(pb, 'home'); shot(pb, '10-permiso-notificaciones-pendiente.png')
    rec('P4c', 'Sin permiso de notificaciones la app lo explica y no intenta mostrar avisos',
        'Estado ≠ granted, texto informativo y botón «Probar» desactivado',
        f'permiso={perm0} · texto="{n0}" · probar desactivado={pb.is_disabled("#ntest")}', perm0 != 'granted' and pb.is_disabled('#ntest') and len(n0) > 20)
    # Flujo completo: el permiso aún no existe -> el usuario lo concede -> se muestra la notificación
    pb.click('#nbtn')                       # el navegador pregunta; la prueba lo autoriza (equivale a pulsar «Permitir»)
    ctxB.grant_permissions(['notifications'], origin=BASE)
    pb.wait_for_timeout(300)
    pb.click('#nbtn') if not pb.is_disabled('#nbtn') else None
    pb.wait_for_function("Notification.permission === 'granted'", timeout=4000)
    pb.wait_for_timeout(1200)
    n_perm = notifs(pb, 'permiso'); est = pb.text_content('#nstate')
    shot(pb, '11-permiso-concedido-notificacion-confirmacion.png')
    rec('P4d', 'Flujo de permiso: solicitar → conceder → se muestra la notificación',
        'Tras conceder el permiso aparece la notificación de confirmación y el estado cambia a «Activadas»',
        f'permiso={pb.evaluate("Notification.permission")} · notificación="{n_perm[0]["title"] if n_perm else None}" · estado="{est[:30]}…"',
        len(n_perm) == 1 and est.startswith('Activadas'))
    ctxB.close()

    # =============== Servidor: API, validación y seguridad
    s, _ = api('/api/incidencias', 'POST', {'id': 'test-geo-1', 'titulo': 'Prueba API', 'prioridad': 'Baja', 'fecha': '2026-10-24T00:00:00Z',
                                          'ubicacion': {'lat': 19.28, 'lng': -99.51, 'precision': 10, 'script': '<x>'}})
    s2, _ = api('/api/incidencias', 'POST', {'id': 'test-geo-2', 'titulo': 'Prueba inválida', 'prioridad': 'Baja', 'fecha': '2026-10-24T00:00:00Z',
                                           'ubicacion': {'lat': 999, 'lng': 'x'}})
    lst = api('/api/incidencias')[1]
    g1 = next(i for i in lst if i['id'] == 'test-geo-1'); g2 = next(i for i in lst if i['id'] == 'test-geo-2')
    api('/api/incidencias/test-geo-1', 'DELETE'); api('/api/incidencias/test-geo-2', 'DELETE')
    codes = {}
    for u in ['/db.json', '/vapid.json', '/subs.json', '/server.js', '/package.json', '/.git/config']:
        try: codes[u] = urllib.request.urlopen(BASE + u).status
        except urllib.error.HTTPError as e: codes[u] = e.code
    rec('S1', 'API: la ubicación se valida y los archivos internos no se exponen',
        'Ubicación válida se guarda (sin campos extra), la inválida se descarta; db.json, vapid.json, server.js y .git responden 404',
        f'válida={g1.get("ubicacion")} · inválida={g2.get("ubicacion")} · códigos={codes}',
        s == 201 and g1.get('ubicacion') == {'lat': 19.28, 'lng': -99.51, 'precision': 10, 'ts': None} and 'ubicacion' not in g2 and set(codes.values()) == {404})
    k = api('/api/push/key'); bad = api('/api/push/subscribe', 'POST', {'x': 1}); unk = api('/api/push/test', 'POST', {'endpoint': 'https://x'})
    ok_sub = api('/api/push/subscribe', 'POST', {'endpoint': 'https://push.invalid/abc', 'keys': {'p256dh': 'a', 'auth': 'b'}})
    api('/api/push/unsubscribe', 'POST', {'endpoint': 'https://push.invalid/abc'})
    rec('S2', 'Servicio de envío push: endpoints y validación',
        'GET /key entrega la clave VAPID pública (87 caracteres); suscripción inválida → 400; prueba sin suscripción → 404; suscripción válida → 201',
        f'key={len(k[1]["key"])} car. · inválida={bad[0]} · desconocida={unk[0]} · válida={ok_sub[0]}',
        k[0] == 200 and len(k[1]['key']) == 87 and bad[0] == 400 and unk[0] == 404 and ok_sub[0] == 201)
    br.close()

ignorados = [e for e in errors]
rec('E1', 'Sin errores de JavaScript no controlados durante todas las pruebas', '0 excepciones en la página', f'{len(ignorados)} excepciones {ignorados[:2]}', not ignorados)
json.dump(R, open(os.path.join(ROOT, 'docs', 'resultados_pruebas.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('\nResumen:', sum(r['estado'] == 'APROBADO' for r in R), '/', len(R), 'aprobadas')
sys.exit(0 if all(r['estado'] == 'APROBADO' for r in R) else 1)
