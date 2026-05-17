# PEARL HOME Operations

## Roles

- Celular/Termux: core principal de usuario, `core.py`, puerto `5004`.
- Laptop: nodo pesado, musica `5005`, orchestrator `5006`, Ollama `11434`.
- Repo oficial para pruebas y GitHub: `/home/samsung-ubuntu/jarvis_core`.
- Repo `pearl-home` en laptop: copia historica/de apoyo. No usar como fuente final sin migrar cambios a `jarvis_core`.

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
