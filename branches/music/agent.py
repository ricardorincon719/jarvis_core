import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import requests

from branches.music_memory import MusicMemory


VERSION = "4.0.0"
DESCRIPTION = "Agente de musica remoto con memoria persistente para el nodo laptop"

LAPTOP_HOST = os.getenv("JARVIS_MUSIC_HOST", "jarvis-node.local")
PORT = int(os.getenv("JARVIS_MUSIC_PORT", "5005"))
BASE_DIR = Path(__file__).resolve().parent
CONNECT_TIMEOUT = float(os.getenv("JARVIS_MUSIC_CONNECT_TIMEOUT", "4"))
STATUS_TIMEOUT = float(os.getenv("JARVIS_MUSIC_STATUS_TIMEOUT", "8"))
CONTROL_TIMEOUT = float(os.getenv("JARVIS_MUSIC_CONTROL_TIMEOUT", "15"))
PLAY_TIMEOUT = float(os.getenv("JARVIS_MUSIC_PLAY_TIMEOUT", "90"))

TRIGGERS = [
    "musica", "música", "pon", "reproduce", "reproducir", "play",
    "pausa", "reanuda", "continua", "continúa", "parar", "detener", "stop",
    "siguiente", "next", "anterior", "previo", "previous", "estado",
    "sonando", "reproductor",
    "laptop", "pc", "nodo", "recuerda", "memoria", "historial",
]

PRESETS = {
    "lofi": "lofi chill out",
    "jazz": "jazz instrumental lounge",
    "relax": "relaxing ambient music",
    "synthwave": "synthwave retro mix",
}

ALLOWED_ACTIONS = {
    "play",
    "pause",
    "resume",
    "stop",
    "next",
    "previous",
    "status",
    "memory_summary",
    "remember_note",
}


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^\w\s%]", " ", text)
    return " ".join(text.split())


def has_any(text: str, words: List[str]) -> bool:
    return any(normalize_text(word) in text for word in words)


class MusicNodeClient:
    def __init__(self, host: str = LAPTOP_HOST, port: int = PORT):
        self.host = host
        self.port = port

    def _url(self, endpoint: str) -> str:
        return f"http://{self.host}:{self.port}{endpoint}"

    def post(self, endpoint: str, payload=None, read_timeout: Optional[float] = None):
        timeout = (CONNECT_TIMEOUT, read_timeout or CONTROL_TIMEOUT)
        res = requests.post(self._url(endpoint), json=payload or {}, timeout=timeout)
        return res.json()

    def get(self, endpoint: str):
        res = requests.get(self._url(endpoint), timeout=(CONNECT_TIMEOUT, STATUS_TIMEOUT))
        return res.json()

    def execute(self, action: str, query: Optional[str] = None) -> Dict:
        if action == "play":
            data = self.post("/play", {"query": query or "music"}, read_timeout=PLAY_TIMEOUT)
            return {
                "respuesta": data.get("message", f"Reproduciendo: {query or 'music'}"),
                "message": data.get("message"),
                "title": data.get("title"),
                "query": data.get("query") or query,
                "status": data,
            }
        if action == "pause":
            data = self.post("/pause")
            return {"respuesta": data.get("message", "Musica en pausa"), "message": data.get("message")}
        if action == "resume":
            data = self.post("/resume")
            return {"respuesta": data.get("message", "Musica reanudada"), "message": data.get("message")}
        if action == "stop":
            data = self.post("/stop")
            return {"respuesta": data.get("message", "Reproduccion detenida"), "message": data.get("message")}
        if action == "next":
            data = self.post("/next")
            return {
                "respuesta": data.get("message", "Siguiente"),
                "message": data.get("message"),
                "title": data.get("title"),
                "query": data.get("query"),
                "status": data,
            }
        if action == "previous":
            data = self.post("/previous")
            return {
                "respuesta": data.get("message", "Anterior"),
                "message": data.get("message"),
                "title": data.get("title"),
                "query": data.get("query"),
                "status": data,
            }
        if action == "status":
            data = self.get("/status")
            return {"respuesta": data.get("message") or "Estado del nodo de musica consultado", "status": data}
        raise ValueError(f"Accion musical no soportada: {action}")

    def status(self) -> Dict:
        return self.get("/status")


class MusicAgent:
    def __init__(self, client: Optional[MusicNodeClient] = None, memory: Optional[MusicMemory] = None):
        memory_dir = Path(os.getenv("JARVIS_MUSIC_AGENT_MEMORY_DIR", str(BASE_DIR / "memory")))
        self.client = client or MusicNodeClient()
        self.memory = memory or MusicMemory(memory_dir, source="jarvis_core.music_agent", target="laptop")

    def can_handle(self, prompt: str) -> bool:
        text = normalize_text(prompt)
        if text in PRESETS:
            return True
        return any(normalize_text(trigger) in text for trigger in TRIGGERS)

    def handle(self, prompt: str) -> Dict:
        normalized = normalize_text(prompt)
        try:
            plan = self.build_plan(prompt)
            response = self.execute_plan(plan, prompt, normalized)
        except requests.exceptions.ReadTimeout as exc:
            plan = {"intent": "timeout", "actions": [], "error": str(exc)}
            node_status = None
            try:
                node_status = self.client.status()
            except Exception as status_exc:
                node_status = {"status": "unknown", "error": str(status_exc)}

            if isinstance(node_status, dict) and node_status.get("status") == "ok":
                response = {
                    "respuesta": (
                        "El nodo de musica si esta conectado, pero tardo demasiado "
                        "resolviendo la cancion con yt-dlp. Intenta de nuevo o usa "
                        "una busqueda mas especifica."
                    ),
                    "cerebro": "MusicNodeAgent",
                    "debug": {"plan": plan, "node_status": node_status},
                }
            else:
                response = {
                    "respuesta": f"Timeout consultando nodo de musica: {exc}",
                    "cerebro": "MusicNodeAgent",
                    "debug": {"plan": plan, "node_status": node_status},
                }
        except Exception as exc:
            plan = {"intent": "error", "actions": [], "error": str(exc)}
            response = {
                "respuesta": f"Error al conectar con nodo de musica: {exc}",
                "cerebro": "MusicNodeAgent",
                "debug": {"plan": plan},
            }

        try:
            self.memory.record_interaction(prompt, normalized, plan, response)
        except Exception as exc:
            response.setdefault("debug", {})["memory_error"] = str(exc)

        return response

    def status(self) -> Dict:
        data = self.client.status()
        data.setdefault("target", "laptop")
        return data

    def build_plan(self, prompt: str) -> Dict:
        text = normalize_text(prompt)

        if self._is_memory_query(text):
            return self._plan("memory_summary", [{"type": "memory_summary"}])

        note = self._extract_note(text)
        if note:
            return self._plan("remember_note", [{"type": "remember_note", "note": note}])

        if "pausa" in text or text == "silencio":
            return self._plan("pause", [{"type": "pause"}])
        if has_any(text, ["reanuda", "reanudar", "continua", "continuar"]):
            return self._plan("resume", [{"type": "resume"}])
        if has_any(text, ["parar", "detener"]) or text == "stop":
            return self._plan("stop", [{"type": "stop"}])
        if has_any(text, ["siguiente", "next"]):
            return self._plan("next", [{"type": "next"}])
        if has_any(text, ["anterior", "previo", "previous"]):
            return self._plan("previous", [{"type": "previous"}])
        if "estado" in text or has_any(text, ["sonando", "reproductor"]):
            return self._plan("status", [{"type": "status"}])

        query = self.resolve_query(text)
        return self._plan("play", [{"type": "play", "query": query}])

    def execute_plan(self, plan: Dict, prompt: str, normalized: str) -> Dict:
        self._validate_plan(plan)
        actions = plan.get("actions") or []
        if not actions:
            return {
                "respuesta": f"No reconoci un comando musical accionable: '{prompt}'",
                "cerebro": "MusicNodeAgent",
                "debug": {"normalized": normalized, "plan": plan},
            }

        action = actions[0]
        action_type = action["type"]

        if action_type == "memory_summary":
            summary = self.memory.summary()
            return {
                "respuesta": (
                    "Memoria musical laptop: "
                    f"{summary['interactions']} interacciones, "
                    f"{summary['music_events']} eventos, "
                    f"ultimo query: {summary.get('last_query') or 'ninguno'}."
                ),
                "cerebro": "MusicNodeAgent",
                "debug": {"plan": plan, "memory": summary},
            }

        if action_type == "remember_note":
            note = self.memory.remember_note(action.get("note") or "", category="user_preference")
            return {
                "respuesta": "Lo guarde en la memoria musical de laptop.",
                "cerebro": "MusicNodeAgent",
                "debug": {"plan": plan, "note": note},
            }

        result = self.client.execute(action_type, action.get("query"))
        result["cerebro"] = "MusicNodeAgent"
        result["debug"] = {"plan": plan}
        event = self.memory.record_music_event(action_type, action.get("query"), result, prompt)
        result["debug"]["music_event"] = event
        return result

    def resolve_query(self, text: str) -> str:
        for preset, query in PRESETS.items():
            if text == preset:
                return query

        query = text
        for key in ["pon", "play", "reproduce", "reproducir", "musica", "música"]:
            query = query.replace(normalize_text(key), "")

        query = re.sub(r"\b(en|por|desde)\s+(la\s+)?(laptop|pc|computadora|notebook|nodo|remoto)\b", " ", query)
        query = re.sub(r"\b(laptop|pc|computadora|notebook|nodo|remoto)\b", " ", query)
        query = " ".join(query.split())

        for preset, preset_query in PRESETS.items():
            if query == preset:
                return preset_query

        return query or "music"

    def _validate_plan(self, plan: Dict):
        for action in plan.get("actions") or []:
            action_type = action.get("type")
            if action_type not in ALLOWED_ACTIONS:
                raise ValueError(f"Accion musical no permitida: {action_type}")
            if action_type == "play" and not isinstance(action.get("query"), str):
                raise ValueError("La accion play necesita query de texto")

    def _plan(self, intent: str, actions: List[Dict]) -> Dict:
        return {
            "agent": "music",
            "target": "laptop",
            "intent": intent,
            "requires_confirmation": False,
            "actions": actions,
        }

    def _is_memory_query(self, text: str) -> bool:
        return (
            "memoria" in text
            or "historial" in text
            or has_any(text, ["que recuerdas", "que aprendiste"])
        ) and has_any(text, ["musica", "music", "laptop", "nodo"])

    def _extract_note(self, text: str) -> Optional[str]:
        for marker in ("recuerda que", "aprende que", "memoriza que"):
            marker = normalize_text(marker)
            if marker in text:
                note = text.split(marker, 1)[1].strip()
                return note if note else None
        return None
