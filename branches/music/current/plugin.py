VERSION = "3.0.0"
DESCRIPTION = "Control remoto de música en laptop"
TRIGGERS = [
    "musica", "música", "pon", "reproduce", "play",
    "pausa", "reanuda", "continua", "continúa",
    "parar", "detener", "stop",
    "siguiente", "next",
    "anterior", "previo", "previous"
]

import requests

LAPTOP_HOST = "jarvis-node.local"
PORT = 5005

def can_handle(pregunta):
    p = pregunta.lower()
    return any(t in p for t in TRIGGERS)

def _post(endpoint, payload=None):
    url = f"http://{LAPTOP_HOST}:{PORT}{endpoint}"
    res = requests.post(url, json=payload or {}, timeout=13)
    return res.json()

def handle(pregunta):
    p = pregunta.lower().strip()

    try:
        # pausa
        if "pausa" in p:
            data = _post("/pause")
            return {"respuesta": data.get("message", "Música en pausa"), "cerebro": "MusicNode"}

        # reanudar
        if "reanuda" in p or "continua" in p or "continúa" in p:
            data = _post("/resume")
            return {"respuesta": data.get("message", "Música reanudada"), "cerebro": "MusicNode"}

        # stop
        if "parar" in p or "detener" in p or p == "stop":
            data = _post("/stop")
            return {"respuesta": data.get("message", "Reproducción detenida"), "cerebro": "MusicNode"}

        # siguiente
        if "siguiente" in p or "next" in p:
            data = _post("/next")
            return {"respuesta": data.get("message", "Siguiente"), "cerebro": "MusicNode"}

        # anterior
        if "anterior" in p or "previo" in p or "previous" in p:
            data = _post("/previous")
            return {"respuesta": data.get("message", "Anterior"), "cerebro": "MusicNode"}

        # play
        query = p
        for k in ["pon", "reproduce", "música", "musica"]:
            query = query.replace(k, "")
        query = query.strip()

        if not query:
            query = "music"

        data = _post("/play", {"query": query})
        return {"respuesta": data.get("message", f"Reproduciendo: {query}"), "cerebro": "MusicNode"}

    except Exception as e:
        return {
            "respuesta": f"Error al conectar con nodo de música: {e}",
            "cerebro": "MusicNode"
        }
