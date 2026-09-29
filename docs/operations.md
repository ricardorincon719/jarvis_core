# PEARL HOME Operations

## Roles

- PEARL Lite: despliegue completo y portable en un solo equipo.
- PEARL Hub: cerebro central 24/7; orquestador `5006`, memoria y nodos.
- PEARL Client: app de control, estado y consentimiento.
- Celular/Termux actual: despliegue transitorio de PEARL Lite, `core.py`, puerto `5004`.
- Laptop actual: primer despliegue de PEARL Hub, musica `5005`, orchestrator `5006`, IA mediante OpenRouter.
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
- `PEARL_ACTION_PROPOSAL_TTL_SECONDS`: segundos disponibles para confirmar una accion; default `180`.
- `PEARL_ACTION_PROPOSALS_FILE`: ubicacion privada opcional del registro de propuestas.
- `JARVIS_SECRET_TOKEN`: token maestro del core; aleatorio y de al menos 32 caracteres, o queda deshabilitado.
- `JARVIS_AUTH_PIN`: PIN de emparejamiento; al menos 6 caracteres, o el emparejamiento queda deshabilitado.
- `JARVIS_CORE_PORT`: puerto del core movil.
- `PEARL_HUB_API_TIMEOUT`: timeout de llamadas del Core al Hub.
- `PEARL_CORE_GATEWAY_TOKEN`: secreto opcional compartido con Hub para que decisiones sensibles solo entren por Core.
- `PEARL_DEVICE_SIGNATURE_MAX_SKEW_SECONDS`: ventana maxima para firmas nativas Android; default `300`.
- `JARVIS_MUSIC_HOST` y `JARVIS_MUSIC_PORT`: nodo de musica.
- `JARVIS_ORCHESTRATOR_URL`: orchestrator laptop.
- `OPENROUTER_API_URL`, `OPENROUTER_API_KEY` y `OPENROUTER_MODEL`: proveedor de IA del plugin `local_ia`.
- `OPENROUTER_SITE_URL`, `OPENROUTER_APP_NAME` y `OPENROUTER_TIMEOUT_SECONDS`: metadatos y timeout opcionales de OpenRouter.
- `PEARL_NOVA_ENABLED=true`: hace de Nova el proveedor primario únicamente del
  plugin determinista `local_ia`; domótica, música, hardware y critical no cambian.
- `PEARL_NOVA_URL`: puente loopback de Jinnex Next, por defecto
  `http://127.0.0.1:5010`.
- `PEARL_NOVA_EVENT_DB`: outbox SQLite durable. Las respuestas compuestas de
  PEARL se envían como observaciones, sin reemplazar su memoria de escenas.

Las consultas de `local_ia` usan `POST /v1/query`. El prefijo inicial selecciona
el asistente sin consultar modelos: `Nova, ...` conserva conversación y
`Codex, analiza/revisa/investiga ...` o `Codex, planifica ...` selecciona la
acción de solo lectura correspondiente. `Codex` sin verbo conocido y los verbos
de escritura aún reservados fallan localmente; nunca se redirigen a Nova u
OpenRouter.

El bus es fail-open: una caída de Nova deja el evento pendiente para reintento y
no modifica la respuesta, confirmación ni ejecución de PEARL. Nova sólo crea
candidatos complejos sin autoridad de autoejecución.
- `JARVIS_SCENE_MEMORY_MIN_REPETITIONS`: eventos minimos para escena candidata. Default: `2`.
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
POST /api/v1/auth/jinnex-watch  # sólo loopback; uso del bridge Jinnex
GET  /api/v1/auth/session
POST /api/v1/auth/logout
```

Las sesiones genéricas nuevas usan audiencia `pearl-client` y scopes
`pearl.ask`, `jinnex.query` y `jinnex.memory.decide`. La ruta interna del reloj
no acepta scopes enviados por el cliente: fija audiencia `jinnex-watch` y la
lista de capacidades de Jinnex en el servidor. `X-Jinnex-Client-Key` sólo se
considera cuando la conexión llega desde loopback y sirve para aislar cuotas de
PIN; no es una credencial de sesión.

## Consentimiento para acciones

El Core clasifica cada plan JSON antes de ejecutarlo. Una accion desconocida se bloquea
por defecto:

- Nivel 0: solo respuesta; no hay acciones en el plan.
- Nivel 1: ejecucion directa para consultas de estado, pausa de musica y control directo
  de luces (encendido, apagado, brillo, temperatura y color).
- Nivel 2: confirmacion para escenas aprendidas o compuestas, reproduccion y otras
  mutaciones. Las futuras acciones de tuneles remotos, mensajeria y automatizacion tambien deben
  registrarse en este nivel.
- Nivel 3: bloqueo para borrado de archivos, exposicion directa de puertos, cambios de
  tokens o configuracion sensible y cualquier tipo de accion no registrado.

En nivel 2 el Core crea una propuesta persistente, la vincula a la sesion que la
solicito y devuelve `requires_confirmation: true`. La aceptacion ejecuta exactamente
ese plan; no acepta un comando nuevo dentro de la decision.

```text
GET  /actions/pending
GET  /api/v1/actions/pending
POST /actions/<proposal_id>/decision
POST /api/v1/actions/<proposal_id>/decision
```

La decision usa `{"decision":"accept|cancel","idempotency_key":"..."}`. Una
propuesta expirada, ya decidida o perteneciente a otra sesion no puede ejecutarse.
Los estados posibles son `pending`, `executing`, `executed`, `cancelled`, `failed`
y `expired`. El registro predeterminado se guarda en:

```text
~/.local/share/pearl-home/action_proposals.json
```

Mientras una sesion tenga una propuesta pendiente, `/ask` y `/ask_stream` resuelven
antes del router las frases exactas `si`, `confirmo`, `confirmar`, `si hazlo`, `no`,
`cancelar` y `rechazar`. La decision solo afecta la propuesta de esa misma sesion. Una propuesta
nueva cancela como `superseded` la anterior de la misma sesion para evitar que una
confirmacion breve sea ambigua.

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
candidata solo la aprueba en Hub; no ejecuta musica ni domotica. Para acceso remoto, el
tunel de Cloudflare expone el Core `:5004`, no el Hub `:5006`:

```text
https://pearl.pearlhome.com.br -> http://localhost:5004
```

La app Android usa esa URL cuando solo dispone de datos moviles. El Core conserva la
autenticacion de sesion y delega internamente al Hub `:5006`; el cliente no debe usar
`https://hub.pearlhome.com.br` como endpoint principal.

Si defines `PEARL_CORE_GATEWAY_TOKEN` con el mismo valor en Core y Hub, el Hub rechazara
decisiones directas que no incluyan el header interno enviado por Core.

## Verificacion rapida

```bash
.venv/bin/python -m py_compile core.py router.py
curl -H "Authorization: Bearer $JARVIS_SECRET_TOKEN" http://127.0.0.1:5004/health
```
