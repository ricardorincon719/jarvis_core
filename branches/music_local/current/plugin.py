VERSION = "1.2.0"
DESCRIPTION = "Reproducción local en celular con yt-dlp + mpv"
TRIGGERS = [
    "musica", "música", "reproduce",
    "lofi", "synthwave", "jazz", "relax",
    "parar", "detener", "stop"
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
    if p in ["stop", "parar", "detener", "pausa", "reanuda", "siguiente", "anterior"]:
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
    for k in ["reproduce", "música", "musica"]:
        query = query.replace(k, "")
    query = query.strip()

    return query if query else "music"


def resolve_stream_url(query):
    cmd = ["yt-dlp", "-f", "bestaudio", "-g", f"ytsearch1:{query}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp no pudo resolver la búsqueda")

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("No se encontró una URL reproducible")

    return lines[0]


def save_state(pid=None, query=None, url=None):
    data = {
        "pid": pid,
        "query": query,
        "url": url,
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
            os.kill(int(pid), signal.SIGTERM)
            time.sleep(0.4)
        except Exception:
            pass

    # limpieza extra por si quedó algún mpv colgado
    subprocess.run(["pkill", "-f", "mpv"], capture_output=True, text=True, timeout=10)

    save_state(pid=None, query=None, url=None)


def play_query(query):
    url = resolve_stream_url(query)

    proc = subprocess.Popen(
        ["mpv", "--no-video", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    save_state(pid=proc.pid, query=query, url=url)
    return url


def handle(pregunta):
    p = pregunta.lower().strip()

    try:
        if "parar" in p or "detener" in p or p == "stop":
            stop_player()
            return {
                "respuesta": "Reproducción detenida.",
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
