# PWA Alerta Campus · Registro de Incidencias

PWA para reportar incidencias del campus: funciona **sin conexión**, avisa con **notificaciones** (locales y push real) y adjunta la **ubicación** del dispositivo.

## Ejecutar
```bash
npm install        # solo necesario para push real (instala web-push)
node server.js     # abrir http://localhost:3000  (Service Worker requiere localhost o HTTPS)
```

## Funcionalidades PWA
| Funcionalidad | Archivo | Detalle |
|---|---|---|
| Service Worker (install · waiting · activate · actualización con aviso) | `sw.js`, `index.html` | Versión de caché en `VERSION` |
| Funcionamiento sin conexión | `sw.js` | Precaché del App Shell + red primero con respaldo en caché; datos en IndexedDB |
| Notificaciones locales | `index.html`, `sw.js` | Alta prioridad, sincronización completa, prueba |
| Notificaciones push reales | `server.js`, `sw.js` | Claves VAPID, suscripción y envío con `web-push` |
| Geolocalización | `index.html` | Tarjeta «Ubicación» en la parte superior de *Nueva* (radar, estado, coordenadas, precisión, mapa) |
| Avisos de «requiere conexión» | `index.html` | Sincronizar, mapa y push |

## Estructura
```
index.html  sw.js  manifest.json  server.js  package.json
icon*.svg  icon-*.png  imag1.png image2-6.png      ← recursos del App Shell
tests/pruebas_e2e.py                                 ← pruebas automáticas
docs/  PLANEACION.md · DOCUMENTO_TECNICO.md · REPORTE_PRUEBAS.md · CAPTURAS.md · capturas/
```

## Cliente vs servidor
* **Cliente:** UI, validación, UUID, IndexedDB, cola de pendientes, Cache API, notificaciones, geolocalización.
* **Servidor:** persistencia (`db.json`), CRUD `/api/incidencias` (idempotente por `id`), `/api/push/*`. Solo sirve una lista blanca de archivos.

## Documentación y evidencias
* [Planeación (Punto 1)](docs/PLANEACION.md)
* [Documento técnico](docs/DOCUMENTO_TECNICO.md)
* [Reporte de pruebas](docs/REPORTE_PRUEBAS.md) · [Capturas justificadas](docs/CAPTURAS.md)

## Pruebas
```bash
node server.js                       # terminal 1
python3 tests/pruebas_e2e.py         # terminal 2  (pip install playwright && playwright install chromium)
```
Última ejecución: **15/15 aprobadas** (detalle en el reporte).

## Limitaciones
* Sin Background Sync: el reintento ocurre al evento `online`, al abrir la app o con el botón.
* Notificaciones y geolocalización requieren HTTPS o `localhost`; en iOS las notificaciones solo funcionan con la app instalada.
* La API no tiene autenticación (alcance escolar).
* Otras limitaciones: ver `docs/DOCUMENTO_TECNICO.md`, sección 5.

## Publicación
URL de la PWA: *(pendiente: agregar aquí la URL publicada)*
