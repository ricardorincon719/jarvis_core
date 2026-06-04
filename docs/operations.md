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

## Prueba del core en laptop

El core no arranca en laptop por accidente. Para una prueba explicita:

```bash
cd /home/samsung-ubuntu/jarvis_core
JARVIS_CORE_DEV_MODE=true /home/samsung-ubuntu/pearl-home/.venv/bin/python core.py
```

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
expiro. El token maestro existente se conserva para compatibilidad y no puede revocarse
mediante el endpoint de cierre de sesion.

## Verificacion rapida

```bash
.venv/bin/python -m py_compile core.py router.py
curl -H "Authorization: Bearer $JARVIS_SECRET_TOKEN" http://127.0.0.1:5004/health
```
