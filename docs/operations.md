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
- `JARVIS_SECRET_TOKEN`: token local del core.
- `JARVIS_CORE_PORT`: puerto del core movil.
- `JARVIS_MUSIC_HOST` y `JARVIS_MUSIC_PORT`: nodo de musica.
- `JARVIS_ORCHESTRATOR_URL`: orchestrator laptop.
- `JARVIS_OLLAMA_URL` y `JARVIS_OLLAMA_MODEL`: IA local.
- `JARVIS_SCENE_MEMORY_MIN_REPETITIONS`: eventos minimos para escena candidata. Default: `4`.
- `JARVIS_SCENE_MEMORY_MIN_UNIQUE_DAYS`: dias unicos minimos para escena candidata. Default: `2`.
- `JARVIS_SCENE_MEMORY_MIN_DATE`: fecha ISO opcional para ignorar eventos anteriores a una correccion fisica/configuracion.
- `SERPAPI_KEY`: vuelos/internet.

## Verificacion rapida

```bash
.venv/bin/python -m py_compile core.py router.py
curl -H "Authorization: Bearer $JARVIS_SECRET_TOKEN" http://127.0.0.1:5004/health
```
