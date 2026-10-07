"""Destellos del router en JARVIS Brain.

Cada vez que Core decide a dónde va una consulta, el cerebelo de la
visualización destella con el destino. Sólo viaja el nombre del destino,
nunca el texto. Un único hilo envía los mensajes en orden; si el hub está
caído se descartan sin afectar a Core. Activo sólo con JINNEX_BRAIN_URL.
"""

import json
import os
import queue
import threading
import urllib.request

ROUTE_LABELS = {
    "local_ia": "Nova",
    "domotica": "domótica",
    "music": "música",
    "music_local": "música",
    "vision": "visión",
    "core_health": "estado del sistema",
    "critical": "crítico",
    "internet": "internet",
    "hardware": "hardware",
    "core": "confirmación",
}

_queue: queue.Queue = queue.Queue(maxsize=100)
_lock = threading.Lock()
_worker: list = []


def route_label(plugins) -> str:
    """'→ domótica' o '→ música + domótica' para una o varias rutas."""
    names = []
    for plugin in plugins:
        label = ROUTE_LABELS.get(plugin, plugin)
        if label not in names:
            names.append(label)
    return "→ " + " + ".join(names)


def _post(message: dict) -> None:
    url = os.environ.get("JINNEX_BRAIN_URL", "")
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("JINNEX_BRAIN_TOKEN", "")
    if token:
        headers["X-Brain-Token"] = token
    request = urllib.request.Request(url, data=json.dumps(message).encode(),
                                     headers=headers, method="POST")
    try:
        urllib.request.urlopen(request, timeout=0.5).close()
    except Exception:
        pass


def _run() -> None:
    while True:
        _post(_queue.get())


def pulse_route(*plugins: str) -> None:
    """Destello del router hacia uno o varios plugins. Nunca bloquea ni falla."""
    if not os.environ.get("JINNEX_BRAIN_URL") or not plugins:
        return
    with _lock:
        if not _worker:
            _worker.append(threading.Thread(target=_run, name="brain-router", daemon=True))
            _worker[0].start()
    try:
        _queue.put_nowait({"phase": "pulse", "region": "router", "source": "jarvis_core",
                           "detail": route_label(plugins)})
    except queue.Full:
        pass
