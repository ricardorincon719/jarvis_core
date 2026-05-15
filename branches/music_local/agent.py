import json
import os
import re
import signal
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from branches.music_memory import MusicMemory


VERSION = "2.0.0"
DESCRIPTION = "Agente de musica local en celular con memoria persistente"

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "current" / "player_state.json"
DEFAULT_NODE_PATH = Path.home() / ".nvm" / "versions" / "node" / "v24.15.0" / "bin" / "node"
YTDLP_FORMATS = [
    value.strip()
    for value in os.getenv("JARVIS_YTDLP_FORMATS", "bestaudio/best[height<=480]/best,best").split(",")
    if value.strip()
]

TRIGGERS = [
    "musica", "música", "reproduce", "reproducir", "lofi", "synthwave",
    "jazz", "relax", "play", "pausa", "reanuda", "continua", "parar",
    "detener", "stop", "siguiente", "next", "anterior", "previo",
    "previous", "silencio", "sube el volumen", "baja el volumen",
    "celular", "telefono", "teléfono", "android", "local", "memoria",
]

PRESETS = {
    "lofi": "lofi chill out",
    "synthwave": "synthwave retro mix",
    "jazz": "jazz instrumental lounge",
    "relax": "relaxing ambient music",
}

ALLOWED_ACTIONS = {
    "play",
    "pause",
    "resume",
    "stop",
    "next",
    "previous",
    "volume_up",
    "volume_down",
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


def node_runtime_path():
    configured = os.getenv("JARVIS_YTDLP_NODE_PATH") or os.getenv("YTDLP_NODE_PATH")
    candidates = [configured, str(DEFAULT_NODE_PATH), shutil.which("node")]

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    return None


def yt_dlp_base_args():
    args = ["yt-dlp"]
    node_path = node_runtime_path()
    if node_path:
        args.extend(["--no-js-runtimes", "--js-runtimes", f"node:{node_path}"])
    return args


def resolve_track_info(query, index=1):
    last_error = None

    for selected_format in YTDLP_FORMATS:
        cmd = [
            *yt_dlp_base_args(),
            "-f",
            selected_format,
            "-g",
            f"ytsearch{index}:{query}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)

        if result.returncode != 0:
            last_error = result.stderr.strip() or "yt-dlp no pudo resolver la busqueda"
            continue

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            last_error = "No se encontro una URL reproducible"
            continue

        return {
            "url": lines[-1],
            "title": query,
            "webpage_url": None,
            "duration": None,
            "thumbnail": None,
        }

    raise RuntimeError(last_error or "yt-dlp no pudo resolver la busqueda")


def resolve_stream_url(query, index=1):
    return resolve_track_info(query, index)["url"]


def resolve_track(query, index=1):
    last_error = None

    for selected_format in YTDLP_FORMATS:
        cmd = [
            *yt_dlp_base_args(),
            "-f",
            selected_format,
            "--dump-json",
            f"ytsearch{index}:{query}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)

        if result.returncode != 0:
            last_error = result.stderr.strip() or "yt-dlp no pudo resolver la busqueda"
            continue

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            last_error = "No se encontro metadata reproducible"
            continue

        try:
            info = json.loads(lines[-1])
        except json.JSONDecodeError:
            last_error = "yt-dlp devolvio metadata invalida"
            continue

        if not info.get("url"):
            last_error = "No se encontro una URL reproducible"
            continue

        return {
            "url": info.get("url"),
            "title": info.get("title") or query,
            "webpage_url": info.get("webpage_url") or info.get("original_url"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
        }

    try:
        return resolve_track_info(query, index)
    except RuntimeError as exc:
        raise RuntimeError(last_error or str(exc))


def save_state(pid=None, query=None, url=None, index=1, paused=False, title=None, webpage_url=None, duration=None, thumbnail=None):
    data = {
        "pid": pid,
        "query": query,
        "url": url,
        "index": index,
        "paused": paused,
        "time": int(time.time()),
        "title": title,
        "webpage_url": webpage_url,
        "duration": duration,
        "thumbnail": thumbnail,
    }
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def pid_is_running(pid):
    if not pid:
        return False

    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def stop_player():
    state = load_state()
    pid = state.get("pid")

    if pid:
        try:
            os.kill(int(pid), signal.SIGCONT)
            os.kill(int(pid), signal.SIGTERM)
            time.sleep(0.4)
        except Exception:
            pass

    subprocess.run(["pkill", "-f", "mpv"], capture_output=True, text=True, timeout=10)
    save_state(pid=None, query=None, url=None)


def pause_player():
    state = load_state()
    pid = state.get("pid")

    if not pid_is_running(pid):
        return False

    os.kill(int(pid), signal.SIGSTOP)
    state["paused"] = True
    save_state(
        pid=state.get("pid"),
        query=state.get("query"),
        url=state.get("url"),
        index=state.get("index", 1),
        paused=True,
        title=state.get("title"),
        webpage_url=state.get("webpage_url"),
        duration=state.get("duration"),
        thumbnail=state.get("thumbnail"),
    )
    return True


def resume_player():
    state = load_state()
    pid = state.get("pid")

    if not pid_is_running(pid):
        return False

    os.kill(int(pid), signal.SIGCONT)
    state["paused"] = False
    save_state(
        pid=state.get("pid"),
        query=state.get("query"),
        url=state.get("url"),
        index=state.get("index", 1),
        paused=False,
        title=state.get("title"),
        webpage_url=state.get("webpage_url"),
        duration=state.get("duration"),
        thumbnail=state.get("thumbnail"),
    )
    return True


def play_query(query, index=1):
    track = resolve_track(query, index)

    proc = subprocess.Popen(
        ["mpv", "--no-video", track["url"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    save_state(
        pid=proc.pid,
        query=query,
        url=track["url"],
        index=index,
        paused=False,
        title=track.get("title"),
        webpage_url=track.get("webpage_url"),
        duration=track.get("duration"),
        thumbnail=track.get("thumbnail"),
    )
    return track["url"]


def replay_saved(delta=0):
    state = load_state()
    query = state.get("query")

    if not query:
        return None, "No hay una reproduccion activa para cambiar."

    current_index = int(state.get("index") or 1)
    next_index = current_index + delta

    if next_index < 1:
        return None, "Ya estas en el primer resultado."

    stop_player()
    play_query(query, next_index)
    return next_index, f"Reproduciendo: {query} (resultado {next_index})"


def run_first_available(commands):
    last_error = None

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return True
            last_error = result.stderr.strip() or result.stdout.strip()
        except FileNotFoundError as e:
            last_error = str(e)
        except Exception as e:
            last_error = str(e)

    return False, last_error


def adjust_termux_volume(direction):
    try:
        result = subprocess.run(["termux-volume"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False

        streams = json.loads(result.stdout)
        music_stream = next(
            (item for item in streams if str(item.get("stream", "")).lower() == "music"),
            None,
        )

        if not music_stream:
            return False

        current = int(music_stream.get("volume", 0))
        maximum = int(music_stream.get("max_volume", 15))
        step = 1 if direction > 0 else -1
        new_volume = max(0, min(maximum, current + step))

        set_result = subprocess.run(
            ["termux-volume", "music", str(new_volume)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return set_result.returncode == 0
    except Exception:
        return False


def adjust_volume(direction):
    if adjust_termux_volume(direction):
        return "Volumen aumentado." if direction > 0 else "Volumen reducido."

    if direction > 0:
        commands = [
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"],
            ["amixer", "sset", "Master", "5%+"],
        ]
        message = "Volumen aumentado."
    else:
        commands = [
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
            ["amixer", "sset", "Master", "5%-"],
        ]
        message = "Volumen reducido."

    result = run_first_available(commands)
    if result is True:
        return message

    return "No pude cambiar el volumen desde este entorno."


class MusicLocalAgent:
    def __init__(self, memory: Optional[MusicMemory] = None):
        memory_dir = Path(os.getenv("JARVIS_MUSIC_LOCAL_MEMORY_DIR", str(BASE_DIR / "memory")))
        self.memory = memory or MusicMemory(memory_dir, source="jarvis_core.music_local_agent", target="cellphone")

    def can_handle(self, prompt: str) -> bool:
        text = normalize_text(prompt)
        if text in PRESETS:
            return True
        if text in [
            "play", "stop", "parar", "detener", "pausa", "reanuda", "reanudar",
            "continua", "continuar", "siguiente", "next", "anterior", "previo",
            "previous", "silencio", "sube el volumen", "baja el volumen",
        ]:
            return True
        music_terms = ["reproduce", "reproducir", "musica", "música", "cancion", "canción", "tema"]
        return any(normalize_text(term) in text for term in music_terms)

    def handle(self, prompt: str) -> Dict:
        normalized = normalize_text(prompt)
        try:
            plan = self.build_plan(prompt)
            response = self.execute_plan(plan, prompt, normalized)
        except Exception as exc:
            plan = {"intent": "error", "actions": [], "error": str(exc)}
            response = {
                "respuesta": f"Error en music_local: {exc}",
                "cerebro": "MusicLocalAgent",
                "debug": {"plan": plan},
            }

        try:
            self.memory.record_interaction(prompt, normalized, plan, response)
        except Exception as exc:
            response.setdefault("debug", {})["memory_error"] = str(exc)

        return response

    def build_plan(self, prompt: str) -> Dict:
        text = normalize_text(prompt)

        if self._is_memory_query(text):
            return self._plan("memory_summary", [{"type": "memory_summary"}])

        note = self._extract_note(text)
        if note:
            return self._plan("remember_note", [{"type": "remember_note", "note": note}])

        if text == "play":
            return self._plan("play_saved", [{"type": "play", "query": None, "use_saved": True}])
        if text in {"pausa", "silencio"}:
            return self._plan("pause", [{"type": "pause"}])
        if text in {"reanuda", "reanudar", "continua", "continuar"}:
            return self._plan("resume", [{"type": "resume"}])
        if "parar" in text or "detener" in text or text == "stop":
            return self._plan("stop", [{"type": "stop"}])
        if text in {"siguiente", "next"}:
            return self._plan("next", [{"type": "next"}])
        if text in {"anterior", "previo", "previous"}:
            return self._plan("previous", [{"type": "previous"}])
        if text == "sube el volumen":
            return self._plan("volume_up", [{"type": "volume_up"}])
        if text == "baja el volumen":
            return self._plan("volume_down", [{"type": "volume_down"}])

        query = self.resolve_query(text)
        return self._plan("play", [{"type": "play", "query": query}])

    def execute_plan(self, plan: Dict, prompt: str, normalized: str) -> Dict:
        self._validate_plan(plan)
        actions = plan.get("actions") or []
        if not actions:
            return {
                "respuesta": f"No reconoci un comando musical local accionable: '{prompt}'",
                "cerebro": "MusicLocalAgent",
                "debug": {"normalized": normalized, "plan": plan},
            }

        action = actions[0]
        action_type = action["type"]

        if action_type == "memory_summary":
            summary = self.memory.summary()
            return {
                "respuesta": (
                    "Memoria musical local: "
                    f"{summary['interactions']} interacciones, "
                    f"{summary['music_events']} eventos, "
                    f"ultimo query: {summary.get('last_query') or 'ninguno'}."
                ),
                "cerebro": "MusicLocalAgent",
                "debug": {"plan": plan, "memory": summary},
            }

        if action_type == "remember_note":
            note = self.memory.remember_note(action.get("note") or "", category="user_preference")
            return {
                "respuesta": "Lo guarde en la memoria musical local.",
                "cerebro": "MusicLocalAgent",
                "debug": {"plan": plan, "note": note},
            }

        result = self._execute_action(action)
        result["debug"] = {"plan": plan}
        event = self.memory.record_music_event(action_type, action.get("query"), result, prompt)
        result["debug"]["music_event"] = event
        return result

    def _execute_action(self, action: Dict) -> Dict:
        action_type = action["type"]

        if action_type == "play":
            if action.get("use_saved"):
                state = load_state()
                if state.get("paused") and resume_player():
                    return {"respuesta": "Musica reanudada.", "cerebro": "MusicLocalAgent"}
                query = state.get("query") or "music"
                index = int(state.get("index") or 1)
            else:
                query = action.get("query") or "music"
                index = 1

            stop_player()
            play_query(query, index)
            state = load_state()
            title = state.get("title") or query
            return {
                "respuesta": f"Reproduciendo: {title}",
                "cerebro": "MusicLocalAgent",
                "title": title,
                "query": query,
            }

        if action_type == "pause":
            if pause_player():
                return {"respuesta": "Musica en pausa.", "cerebro": "MusicLocalAgent"}
            return {"respuesta": "No hay reproduccion activa para pausar.", "cerebro": "MusicLocalAgent"}

        if action_type == "resume":
            if resume_player():
                return {"respuesta": "Musica reanudada.", "cerebro": "MusicLocalAgent"}
            return {"respuesta": "No hay reproduccion activa para reanudar.", "cerebro": "MusicLocalAgent"}

        if action_type == "stop":
            stop_player()
            return {"respuesta": "Reproduccion detenida.", "cerebro": "MusicLocalAgent"}

        if action_type == "next":
            _, message = replay_saved(delta=1)
            return {"respuesta": message, "cerebro": "MusicLocalAgent"}

        if action_type == "previous":
            _, message = replay_saved(delta=-1)
            return {"respuesta": message, "cerebro": "MusicLocalAgent"}

        if action_type == "volume_up":
            return {"respuesta": adjust_volume(1), "cerebro": "MusicLocalAgent"}

        if action_type == "volume_down":
            return {"respuesta": adjust_volume(-1), "cerebro": "MusicLocalAgent"}

        raise ValueError(f"Accion musical local no soportada: {action_type}")

    def status(self) -> Dict:
        state = load_state()
        running = pid_is_running(state.get("pid"))
        return {
            "status": "ok",
            "target": "cellphone",
            "running": running,
            "playing": running and not bool(state.get("paused")),
            "paused": bool(state.get("paused")),
            "query": state.get("query"),
            "index": state.get("index"),
            "title": state.get("title") or state.get("query"),
            "webpage_url": state.get("webpage_url"),
            "duration": state.get("duration"),
            "thumbnail": state.get("thumbnail"),
        }

    def resolve_query(self, text: str) -> str:
        for preset, query in PRESETS.items():
            if text == preset:
                return query

        query = text
        for key in ["pon", "play", "reproduce", "reproducir", "musica", "música"]:
            query = query.replace(normalize_text(key), "")
        query = re.sub(r"\b(en|por|desde)\s+(el\s+)?(celular|telefono|android|local)\b", " ", query)
        query = re.sub(r"\b(celular|telefono|android|local|aca|aqui)\b", " ", query)
        query = " ".join(query.split())

        for preset, preset_query in PRESETS.items():
            if query == preset:
                return preset_query

        return query or "music"

    def _validate_plan(self, plan: Dict):
        for action in plan.get("actions") or []:
            action_type = action.get("type")
            if action_type not in ALLOWED_ACTIONS:
                raise ValueError(f"Accion musical local no permitida: {action_type}")
            if action_type == "play" and action.get("query") is not None and not isinstance(action.get("query"), str):
                raise ValueError("La accion play necesita query de texto")

    def _plan(self, intent: str, actions: List[Dict]) -> Dict:
        return {
            "agent": "music_local",
            "target": "cellphone",
            "intent": intent,
            "requires_confirmation": False,
            "actions": actions,
        }

    def _is_memory_query(self, text: str) -> bool:
        return (
            "memoria" in text
            or "historial" in text
            or has_any(text, ["que recuerdas", "que aprendiste"])
        ) and has_any(text, ["musica", "music", "celular", "local"])

    def _extract_note(self, text: str) -> Optional[str]:
        for marker in ("recuerda que", "aprende que", "memoriza que"):
            marker = normalize_text(marker)
            if marker in text:
                note = text.split(marker, 1)[1].strip()
                return note if note else None
        return None
