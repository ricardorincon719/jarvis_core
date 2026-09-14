# PEARL HOME powered by Jarvis

Core local de PEARL HOME. Coordina la interfaz del cliente, autenticación, plugins, IA local, domótica, música, memoria de escenas y acciones que requieren consentimiento humano.

El asistente se identifica como **JARVIS** y su nombre interno en este proyecto es **Nodo**.

> Estado actual: Beta `0.7.0-beta.1`.

## Principios

```text
IA propone → persona confirma → Core valida → nodo ejecuta
```

- La salida libre de un modelo nunca ejecuta directamente hardware o comandos físicos.
- Las acciones se representan como planes JSON y se validan contra una lista permitida.
- Las escenas aprendidas requieren aprobación y una confirmación adicional para ejecutarse.
- El Core mantiene compatibilidad con los contratos existentes durante la Beta.
- El celular es principalmente cliente y control remoto; la laptop es el Hub principal.

## Arquitectura

```text
PEARL Client / Web UI / Android
              |
              v
PEARL Core :5004
autenticación · router · plugins · políticas · propuestas
              |
       +------+------+
       |             |
       v             v
PEARL Hub :5006   Música :5005
orquestador       mpv / yt-dlp
IA · memoria      reproducción
escenas
       |
       v
Domótica / hardware local
```

| Componente | Responsabilidad | Ubicación habitual |
| --- | --- | --- |
| PEARL Core | Gateway Flask, autenticación, routing, plugins, seguridad y propuestas | Este repositorio |
| PEARL Hub | Orquestación de laptop, IA, memoria y escenas | `/home/samsung-ubuntu/asistente_local` |
| Nodo de música | Reproducción con mpv y búsqueda con yt-dlp | `/home/samsung-ubuntu/jarvis_node` |
| PEARL Client | Interfaz, sesiones, consentimiento y notificaciones | Android/Web |
| Plugin domótica | Luces, dispositivos Tuya, descubrimiento y memoria | `branches/domotica` |

Puertos del despliegue de referencia:

- `5004`: Core Gateway.
- `5005`: nodo de música.
- `5006`: orquestador PEARL Hub.
- IA conversacional: Nova y el IntentRouter determinista de Codex en Jinnex Next
  mediante puente local; OpenRouter queda como fallback si el puente no está
  disponible para una consulta normal de Nova. Una solicitud explícita a Codex
  nunca cambia de proveedor silenciosamente.

El nombre de red habitual de la laptop desde el celular es `jarvis-node.local`.

### Memorias Jinnex y observador Nova

Con una sesión de dispositivo vinculada, las propuestas de memoria muestran un
resumen y los comandos `/confirmar_memoria ID_PROPUESTA` y
`/rechazar_memoria ID_PROPUESTA`. `/memorias_pendientes` recupera la lista del
servidor. Core intercepta esos comandos antes del router/modelo; las propuestas
estructuradas se conservan también en el evento final de streaming. El token
maestro no autoriza estas decisiones y un canal distinto no decide la propuesta.
Requiere el bridge Jinnex con el contrato de confirmación activado.

Cuando `PEARL_NOVA_ENABLED=true`, el arranque de Core inicia la outbox existente
sin necesitar una nueva publicación. La entrega valida un candidato del evento
original con `auto_execute=false`; los fallos usan backoff hasta ocho intentos y
descarte con evidencia. El observador no repite la orden física. Un fallo de
inicialización se registra sin impedir el arranque del Core.

Los cambios F01–F06 están activados desde el 2026-09-14, con respaldos privados,
preparación de Nova y pruebas funcionales reales. La outbox preexistente quedó
entregada sin repetir órdenes físicas. El reporte completo y el runner aislado están en
`/home/samsung-ubuntu/A_proyecto_nuevo/Jinnex_Next/docs/f01-f06.md` y
`docs/f01-f06/run_pearl_tests.py` del mismo checkout Jinnex.

## Ediciones

### PEARL Lite

Despliegue portable en un solo equipo, Android/Termux o una instalación mínima. Puede ejecutar Core, plugins, luces, música y escenas simples sin depender de un Hub externo.

### PEARL Hub

Cerebro central para funcionamiento continuo. Coordina IA, memoria, escenas, nodos y servicios del hogar. En el despliegue actual vive en la laptop.

### PEARL Client

Aplicación de control y consentimiento. Registra dispositivos autorizados, consulta estado, muestra propuestas y acepta o cancela acciones. No ejecuta hardware directamente.

Detalles en [docs/product-editions.md](docs/product-editions.md).

## Requisitos e instalación

- Python 3.12 recomendado para el entorno actual.
- Entorno virtual Python y dependencias de [requirements.txt](requirements.txt).
- Una API key de OpenRouter para IA.
- mpv y yt-dlp para el nodo de música.
- Dispositivos Tuya y sus credenciales para domótica local.

Instalación nueva:

```bash
cd /home/samsung-ubuntu/jarvis_core
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` antes de iniciar. Nunca publiques ese archivo ni credenciales, tokens, conversaciones o memoria real.

## Inicio rápido

### Ejecución manual

```bash
cd /home/samsung-ubuntu/jarvis_core
.venv/bin/python core.py
```

El Core queda disponible en `http://127.0.0.1:5004` o en la interfaz LAN configurada.

### Servicio persistente en Linux

El instalador crea y habilita `pearl-core.service` como servicio `systemd --user`:

```bash
cd /home/samsung-ubuntu/jarvis_core
./scripts/install_core_service.sh
```

Operación habitual:

```bash
systemctl --user status pearl-core.service
systemctl --user restart pearl-core.service
journalctl --user -u pearl-core.service -f
```

La unidad usa `.venv/bin/python`, reinicia automáticamente el Core y carga `.env`.

### Termux

```bash
cd ~/JARVIS_CORE
python core.py
```

Scripts disponibles: `start_core_if_needed_termux.sh`, `restart_core_termux.sh` e `install_termux_shell_autostart.sh`.

## Configuración

La plantilla completa está en [.env.example](.env.example). Variables principales:

| Variable | Uso | Predeterminado |
| --- | --- | --- |
| `PEARL_PRODUCT` | Nombre del producto | `PEARL Lite` |
| `PEARL_EDITION` | Edición activa | `lite` |
| `PEARL_VERSION` | Versión de API/producto | `0.7.0-beta.1` |
| `JARVIS_SECRET_TOKEN` | Token maestro local | `jarvis_local_123` |
| `JARVIS_CORE_HOST` / `JARVIS_CORE_PORT` | Escucha del Core | `0.0.0.0` / `5004` |
| `JARVIS_ORCHESTRATOR_URL` | URL del Hub | `http://jarvis-node.local:5006` |
| `JARVIS_MUSIC_HOST` / `JARVIS_MUSIC_PORT` | Nodo musical | `jarvis-node.local` / `5005` |
| `OPENROUTER_API_URL` | API base de OpenRouter | `https://openrouter.ai/api/v1` |
| `OPENROUTER_API_KEY` | Credencial del proveedor | Obligatoria |
| `OPENROUTER_MODEL` | Modelo remoto | `deepseek/deepseek-v4-flash` |
| `OPENROUTER_SITE_URL` / `OPENROUTER_APP_NAME` | Metadatos opcionales | Vacío / `PEARL HOME` |
| `OPENROUTER_TIMEOUT_SECONDS` | Timeout de generación | `120` segundos |
| `PEARL_NOVA_ENABLED` | Delega sólo `local_ia` a Nova | `false` |
| `PEARL_NOVA_URL` | Puente local de Jinnex Next | `http://127.0.0.1:5010` |
| `PEARL_NOVA_SESSION_ID` | Sesión conversacional durable de la consola | `pearl:console:user:ricardo` |
| `PEARL_NOVA_EVENT_DB` | Outbox SQLite de eventos para Nova | `~/.local/share/pearl-home/nova_event_bus.db` |
| `PEARL_HUB_API_TIMEOUT` | Timeout hacia el Hub | `8` segundos |
| `PEARL_ACTION_PROPOSAL_TTL_SECONDS` | Vida de una propuesta | `180` segundos |
| `PEARL_DEVICE_SESSIONS_FILE` | Sesiones persistentes | `~/.local/share/pearl-home/device_sessions.json` |
| `PEARL_ACTION_PROPOSALS_FILE` | Propuestas persistentes | `~/.local/share/pearl-home/action_proposals.json` |
| `JARVIS_SCENE_MEMORY_MIN_REPETITIONS` | Repeticiones para candidato | `2` |
| `JARVIS_SCENE_MEMORY_MIN_UNIQUE_DAYS` | Días únicos para candidato | `2` |

Para una instalación real, cambia especialmente `JARVIS_SECRET_TOKEN` y las claves de Tuya. El valor de `.env.example` es solo de desarrollo.

## Autenticación y seguridad

Las peticiones autenticadas usan:

```http
Authorization: Bearer <token>
```

El primer registro de un dispositivo se realiza mediante PIN. El Core crea un token de sesión, guarda únicamente su hash y permite revocarlo. Android puede asociar la sesión a una clave pública generada con Keystore y firmar peticiones sensibles.

El token maestro se conserva por compatibilidad, pero debe mantenerse local y no distribuirse a clientes.

### Política de acciones

- **Nivel 0:** respuestas sin efectos físicos.
- **Nivel 1:** consultas de estado, pausa de música y controles directos permitidos.
- **Nivel 2:** reproducción, escenas y acciones compuestas; requieren confirmación.
- **Nivel 3:** acciones bloqueadas, como borrar archivos, exponer puertos o modificar credenciales/configuración sensible.

Una confirmación ejecuta exactamente la propuesta almacenada. Las propuestas tienen expiración, propietario de sesión, idempotencia y estados `pending`, `executing`, `executed`, `cancelled`, `failed` o `expired`.

## API del Core

La API estable nueva usa `/api/v1`; durante la Beta se mantienen rutas compatibles sin ese prefijo cuando existen.

### Salud y conversación

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/health`, `/api/v1/health` | Estado, versión, plugins y memoria |
| `GET` | `/ai/status` | Estado de IA local/cloud |
| `GET` | `/network` | URLs locales y dirección LAN |
| `GET` | `/plugins` | Plugins cargados y versiones |
| `POST` | `/ask` | Procesa una consulta JSON |
| `POST` | `/ask_stream` | Consulta con respuesta streaming |
| `POST` | `/ask_auth`, `/api/v1/auth/pin` | Autoriza por PIN |
| `GET` | `/auth/session`, `/api/v1/auth/session` | Valida una sesión |
| `POST` | `/auth/logout`, `/api/v1/auth/logout` | Revoca una sesión |

Ejemplos:

```bash
curl http://127.0.0.1:5004/health

curl -X POST http://127.0.0.1:5004/ask \
  -H 'Authorization: Bearer TU_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"pregunta":"¿qué puedes hacer?"}'

curl -X POST http://127.0.0.1:5004/api/v1/auth/pin \
  -H 'Content-Type: application/json' \
  -d '{"pin":"TU_PIN","device_id":"phone-1","device_name":"PEARL Client"}'
```

### Dispositivos y domótica

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/devices` | Dispositivos registrados |
| `GET` | `/devices/status` | Estados actuales |
| `POST` | `/devices/discover` | Descubrimiento |
| `GET` | `/devices/candidates` | Candidatos pendientes |
| `POST` | `/devices/candidates/<id>/approve` | Aprueba un candidato |
| `POST` | `/devices/candidates/<id>/reject` | Rechaza un candidato |
| `PUT` | `/devices/<name>/local-key` | Actualiza la clave local |

### Escenas y memoria

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/scenes` | Lista escenas, opcionalmente por estado |
| `GET` | `/scenes/candidates` | Escenas candidatas |
| `GET` | `/scenes/events` | Eventos registrados |
| `POST` | `/scenes/suggest` | Sugiere una escena por contexto |
| `POST` | `/scenes/<id>/approve` | Aprueba una candidata |
| `POST` | `/scenes/<id>/reject` | Rechaza una candidata |
| `GET` | `/scene-prompts/pending` | Propuestas pendientes del Hub |
| `POST` | `/scene-prompts/<id>/decision` | Acepta/cancela una propuesta |

### Propuestas de acciones

```text
GET  /actions/pending
POST /actions/<proposal_id>/decision
GET  /api/v1/actions/pending
POST /api/v1/actions/<proposal_id>/decision
```

El cuerpo de una decisión es:

```json
{
  "decision": "accept",
  "idempotency_key": "decision-unique-001"
}
```

Se acepta `accept` o `cancel`. Las frases `sí`, `confirmo`, `confirmar`, `no`, `cancelar` y `rechazar` también se resuelven cuando existe una propuesta para la misma sesión.

## Música

El nodo de música mantiene su API directa en `http://jarvis-node.local:5005`:

| Método | Ruta | Cuerpo |
| --- | --- | --- |
| `POST` | `/play` | `{"query":"jazz instrumental"}` |
| `POST` | `/pause` | — |
| `POST` | `/resume` | — |
| `POST` | `/stop` | — |
| `POST` | `/next` | — |
| `POST` | `/previous` | — |
| `GET` | `/status` | — |

Usa `yt-dlp`, `mpv` y `/tmp/jarvis-mpv.sock`. El plugin musical existente debe conservar este contrato.

## Plugins

El Core escanea `branches/` y carga `branches/<nombre>/current/plugin.py`. Un plugin válido expone `handle()` y puede declarar:

```python
VERSION = "1.0.0"
DESCRIPTION = "Descripción del plugin"
TRIGGERS = ["palabra clave"]
```

Plugins presentes: `auth`, `comandos`, `domotica`, `hardware`, `internet`, `local_ia`, `music`, `music_local`, `critical` y `test`.

Las carpetas versionadas pueden usar un enlace `current` para elegir la versión activa. Si existe `integrity.json`, el Core verifica hashes antes de cargar el plugin.

## Memoria y escenas

Los eventos se almacenan como JSON estructurado:

```json
{
  "intent": "programar",
  "music": {"query": "jazz instrumental", "genre": "jazz"},
  "lights": {"color": "warm_white", "brightness": 45},
  "source": "phone_orchestrator"
}
```

Una escena candidata se crea al alcanzar las repeticiones y días únicos configurados. La coincidencia considera intención, música, color/escena, brillo y ventana horaria.

Toda escena debe conservar:

```json
{
  "requires_confirmation": true,
  "auto_execute": false
}
```

## Estructura del repositorio

```text
core.py                 Gateway Flask y ciclo principal
router.py               Clasificación y routing de consultas
action_policy.py        Niveles de seguridad
action_proposals.py     Persistencia de propuestas
device_sessions.py      Sesiones revocables
assistant_identity.py   Identidad de JARVIS/PEARL
branches/               Plugins y memoria de escenas
deploy/systemd/         Plantilla del servicio systemd
scripts/                Instalación y operación
static/                 JavaScript, CSS e iconos
templates/              Plantillas HTML
tests/                  Pruebas automatizadas
docs/                   Diseño, operaciones y ediciones
```

## Pruebas y verificación

```bash
cd /home/samsung-ubuntu/jarvis_core
.venv/bin/python -m py_compile core.py router.py
.venv/bin/python -m pytest
curl -H "Authorization: Bearer $JARVIS_SECRET_TOKEN" \
  http://127.0.0.1:5004/health
```

Antes de probar acciones físicas, verifica el dispositivo y el nodo destino. Las pruebas deben cubrir expiración, doble confirmación, idempotencia, pérdida de red y reinicio del Core.

## Documentación complementaria

- [Operaciones y configuración](docs/operations.md)
- [Diseño de PEARL HOME Beta Final](docs/beta-final-design.md)
- [Ediciones y compatibilidad](docs/product-editions.md)
- [Variables de entorno](.env.example)
- [Servicio systemd](deploy/systemd/pearl-core.service.in)

## Reglas de contribución

- Mantener los contratos HTTP existentes y agregar capacidades de forma compatible.
- No subir `.env`, tokens, claves Tuya, memoria real, conversaciones ni datos del hogar.
- No ejecutar acciones físicas desde texto libre de un modelo.
- Mantener la separación entre Core, Hub, cliente, música y domótica.
- Añadir pruebas para cambios de seguridad, autenticación, escenas o contratos API.
- Documentar cambios de versión, endpoints o variables de entorno.

## Licencia

Consulta [LICENSE](LICENSE).

## Nombre general Jarvis · 2026-09-14

Jarvis es el nombre general visible del sistema. Las solicitudes «Jarvis, …»
entran al router de Jinnex por `local_ia`, con sesión autenticada cuando procede.
Jinnex deriva órdenes del hogar a PEARL, análisis/planificación a Codex y la
conversación a Nova. PEARL conserva sus reglas y confirmaciones; las propuestas
«guarda en Jarvis» conservan aprobación humana obligatoria. Se mantienen los
identificadores y nombres anteriores por compatibilidad. Ver el reporte
`/home/samsung-ubuntu/A_proyecto_nuevo/Jinnex_Next/docs/jarvis.md`.

## Salud verificada de Nova · F10

La disponibilidad de Nova se obtiene de `liveness` y `readiness`, con estado de
dependencias e instante de comprobación. `nova=connected` aislado no basta.
Los fallos semánticos son visibles como degradación y no se afirma que el modelo
OpenRouter esté cargado localmente. Core `/health` incluye métricas agregadas
de la outbox, edad de pendientes y último intento, sin preguntas ni identidades.
Detalle: `/home/samsung-ubuntu/A_proyecto_nuevo/Jinnex_Next/docs/f07-f10.md`.
