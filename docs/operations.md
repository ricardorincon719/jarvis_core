# PEARL HOME Operations

## Roles

- PEARL Lite: despliegue completo y portable en un solo equipo.
- PEARL Hub: cerebro central 24/7; orquestador `5006`, memoria y nodos.
- PEARL Client: app de control, estado y consentimiento.
- Celular/Termux actual: despliegue transitorio de PEARL Lite, `core.py`, puerto `5004`.
- Laptop actual: primer despliegue de PEARL Hub, musica `5005`, orchestrator `5006`, Ollama `11434`.
- Repo oficial para pruebas y GitHub: `/home/samsung-ubuntu/jarvis_core`.
- Repo `pearl-home` en laptop: copia historica/de apoyo. No usar como fuente final sin migrar cambios a `jarvis_core`.

La version Beta compartida entre productos es `0.7.0-beta.1`. Cada producto informa su
edicion y version en su endpoint de salud. Los contratos HTTP mantienen compatibilidad y
los nuevos contratos estables se publican bajo `/api/v1`.

## Core movil

En Termux:

```bash
cd ~/JARVIS_CORE
python core.py
```

## Core en laptop Hub

El Core se ejecuta como servicio persistente `systemd --user` porque este equipo es el Hub principal:

```bash
cd /home/samsung-ubuntu/jarvis_core
./scripts/install_core_service.sh
```

Operaciones:

```bash
systemctl --user status pearl-core.service
systemctl --user restart pearl-core.service
journalctl --user -u pearl-core.service -f
```

La unidad usa `.venv/bin/python`, reinicia el Core automaticamente y carga la configuracion desde el `.env` local mediante `core.py`. La autenticacion de clientes, sesiones y tokens permanece activa.

Health check:

```bash
curl http://127.0.0.1:5004/health
```

## Configuracion

Crear `.env` local a partir de `.env.example` y no subirlo a git.

Variables principales:

- `PEARL_PRODUCT`, `PEARL_EDITION` y `PEARL_VERSION`: identidad del despliegue.
- `JARVIS_SESSION_TTL_SECONDS`: duracion de una sesion recordada; default `2592000` segundos.
- `PEARL_DEVICE_SESSION_MAX`: cantidad maxima de dispositivos recordados.
- `PEARL_DEVICE_SESSIONS_FILE`: ubicacion privada opcional para sesiones persistentes.
- `JARVIS_SECRET_TOKEN`: token local del core.
- `JARVIS_CORE_PORT`: puerto del core movil.
- `PEARL_HUB_API_TIMEOUT`: timeout de llamadas del Core al Hub.
- `PEARL_CORE_GATEWAY_TOKEN`: secreto opcional compartido con Hub para que decisiones sensibles solo entren por Core.
- `PEARL_DEVICE_SIGNATURE_MAX_SKEW_SECONDS`: ventana maxima para firmas nativas Android; default `300`.
- `JARVIS_MUSIC_HOST` y `JARVIS_MUSIC_PORT`: nodo de musica.
- `JARVIS_ORCHESTRATOR_URL`: orchestrator laptop.
- `JARVIS_OLLAMA_URL` y `JARVIS_OLLAMA_MODEL`: IA local.
- `JARVIS_SCENE_MEMORY_MIN_REPETITIONS`: eventos minimos para escena candidata. Default: `4`.
- `JARVIS_SCENE_MEMORY_MIN_UNIQUE_DAYS`: dias unicos minimos para escena candidata. Default: `2`.
- `JARVIS_SCENE_MEMORY_MIN_DATE`: fecha ISO opcional para ignorar eventos anteriores a una correccion fisica/configuracion.
- `SERPAPI_KEY`: vuelos/internet.

## Sesiones de dispositivo

El PIN sigue siendo obligatorio para autorizar un dispositivo por primera vez. El Core
entrega un token aleatorio y guarda solamente su hash en:

```text
~/.local/share/pearl-home/device_sessions.json
```

Contratos compatibles:

```text
POST /ask_auth
POST /api/v1/auth/pin
GET  /api/v1/auth/session
POST /api/v1/auth/logout
```

La interfaz web recuerda el token, lo valida al abrir y vuelve al PIN si fue revocado o
expiro. En Android, el WebView registra una clave publica generada con Keystore; los
workers nativos firman cada consulta/decision de propuestas con esa identidad. El token
maestro existente se conserva para compatibilidad y no puede revocarse mediante el
endpoint de cierre de sesion.

## Gateway de propuestas

Client debe consultar propuestas a traves del Core autorizado. Android usa sesion
persistente mas firma nativa; no debe llamar directo al Hub. El Core delega al Hub:

```text
GET  /api/v1/scene-prompts/pending
POST /api/v1/scene-prompts/<prompt_id>/decision
```

Si el Hub no esta disponible, el Core responde `503 hub_unavailable`. Aceptar una escena
candidata solo la aprueba en Hub; no ejecuta musica ni domotica. Para acceso remoto con
ngrok, expone el Core `:5004`, no el Hub `:5006`, por ejemplo:

```bash
ngrok http 5004
```

Si defines `PEARL_CORE_GATEWAY_TOKEN` con el mismo valor en Core y Hub, el Hub rechazara
decisiones directas que no incluyan el header interno enviado por Core.

## Verificacion rapida

```bash
.venv/bin/python -m py_compile core.py router.py
curl -H "Authorization: Bearer $JARVIS_SECRET_TOKEN" http://127.0.0.1:5004/health
```
