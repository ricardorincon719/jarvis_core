VERSION = "1.2.0"
DESCRIPTION = "Reproducción local en celular con yt-dlp + mpv"
TRIGGERS = [
    "musica", "música", "reproduce",
    "lofi", "synthwave", "jazz", "relax",
    "play", "pausa", "reanuda", "continua",
    "parar", "detener", "stop",
    "siguiente", "next", "anterior", "previo", "previous",
    "silencio", "sube el volumen", "baja el volumen"
]

import json
import subprocess
import time
import os
import signal
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent / "player_state.json"

PRESETS = {
    "lofi": "lofi chill out",
    "synthwave": "synthwave retro mix",
    "jazz": "jazz instrumental lounge",
    "relax": "relaxing ambient music"
}


def can_handle(pregunta):
    p = pregunta.lower().strip()

    # Presets exactos
    if p in PRESETS:
        return True

    # Comandos de control exactos
    if p in [
        "play", "stop", "parar", "detener",
        "pausa", "reanuda", "reanudar", "continua", "continuar",
        "siguiente", "next", "anterior", "previo", "previous",
        "silencio", "sube el volumen", "baja el volumen"
    ]:
        return True

    # Música solo si viene con verbo musical claro
    music_terms = [
        "reproduce", "reproducir", "música", "musica",
        "música", "musica", "canción", "cancion", "tema"
    ]

    return any(t in p for t in music_terms)
   
    print("PROMPT:", p)
    for t in TRIGGERS:
        if t in p:
            print("MATCH:", t) 
 

def resolve_query(prompt_lower):
    for preset, query in PRESETS.items():
        if preset in prompt_lower:
            return query

    query = prompt_lower
    for k in ["pon", "play", "reproduce", "reproducir", "música", "musica"]:
        query = query.replace(k, "")
    query = query.strip()

    return query if query else "music"


def resolve_stream_url(query, index=1):
    cmd = ["yt-dlp", "-f", "bestaudio", "-g", f"ytsearch{index}:{query}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp no pudo resolver la búsqueda")

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("No se encontró una URL reproducible")

    return lines[-1]


def save_state(pid=None, query=None, url=None, index=1, paused=False):
    data = {
        "pid": pid,
        "query": query,
        "url": url,
        "index": index,
        "paused": paused,
        "time": int(time.time())
    }
    try:
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


def stop_player():
    state = load_state()
    pid = state.get("pid")

    # intenta matar el mpv guardado
    if pid:
        try:
            os.kill(int(pid), signal.SIGCONT)
            os.kill(int(pid), signal.SIGTERM)
            time.sleep(0.4)
        except Exception:
            pass

    # limpieza extra por si quedó algún mpv colgado
    subprocess.run(["pkill", "-f", "mpv"], capture_output=True, text=True, timeout=10)

    save_state(pid=None, query=None, url=None)


def pid_is_running(pid):
    if not pid:
        return False

    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


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
        paused=True
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
        paused=False
    )
    return True


def play_query(query, index=1):
    url = resolve_stream_url(query, index)

    proc = subprocess.Popen(
        ["mpv", "--no-video", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    save_state(pid=proc.pid, query=query, url=url, index=index, paused=False)
    return url


def replay_saved(delta=0):
    state = load_state()
    query = state.get("query")

    if not query:
        return None, "No hay una reproducción activa para cambiar."

    current_index = int(state.get("index") or 1)
    next_index = current_index + delta

    if next_index < 1:
        return None, "Ya estás en el primer resultado."

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
            None
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
            timeout=5
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


def handle(pregunta):
    p = pregunta.lower().strip()

    try:
        if p == "play":
            state = load_state()
            if state.get("paused") and resume_player():
                return {
                    "respuesta": "Música reanudada.",
                    "cerebro": "MusicLocal"
                }

            query = state.get("query") or "music"
            index = int(state.get("index") or 1)
            stop_player()
            play_query(query, index)
            return {
                "respuesta": f"Reproduciendo: {query}",
                "cerebro": "MusicLocal"
            }

        if p == "pausa":
            if pause_player():
                return {
                    "respuesta": "Música en pausa.",
                    "cerebro": "MusicLocal"
                }
            return {
                "respuesta": "No hay reproducción activa para pausar.",
                "cerebro": "MusicLocal"
            }

        if p in ["reanuda", "reanudar", "continua", "continuar"]:
            if resume_player():
                return {
                    "respuesta": "Música reanudada.",
                    "cerebro": "MusicLocal"
                }
            return {
                "respuesta": "No hay reproducción activa para reanudar.",
                "cerebro": "MusicLocal"
            }

        if p == "silencio":
            if pause_player():
                return {
                    "respuesta": "Música en pausa.",
                    "cerebro": "MusicLocal"
                }
            return {
                "respuesta": "No hay reproducción activa para silenciar.",
                "cerebro": "MusicLocal"
            }

        if p == "sube el volumen":
            return {
                "respuesta": adjust_volume(1),
                "cerebro": "MusicLocal"
            }

        if p == "baja el volumen":
            return {
                "respuesta": adjust_volume(-1),
                "cerebro": "MusicLocal"
            }

        if "parar" in p or "detener" in p or p == "stop":
            stop_player()
            return {
                "respuesta": "Reproducción detenida.",
                "cerebro": "MusicLocal"
            }

        if p in ["siguiente", "next"]:
            _, message = replay_saved(delta=1)
            return {
                "respuesta": message,
                "cerebro": "MusicLocal"
            }

        if p in ["anterior", "previo", "previous"]:
            _, message = replay_saved(delta=-1)
            return {
                "respuesta": message,
                "cerebro": "MusicLocal"
            }

        query = resolve_query(p)

        # detener lo anterior antes de arrancar algo nuevo
        stop_player()
        play_query(query)

        return {
            "respuesta": f"Reproduciendo: {query}",
            "cerebro": "MusicLocal"
        }

    except Exception as e:
        return {
            "respuesta": f"Error en music_local: {e}",
            "cerebro": "MusicLocal"
        }
