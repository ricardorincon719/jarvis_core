VERSION = "1.1.0"
DESCRIPTION = "Reproductor de música desde YouTube (yt-dlp + mpv)"
TRIGGERS = ["musica", "música", "pon", "reproduce", "play"]

import subprocess
import shlex

def can_handle(pregunta: str) -> bool:
    keywords = ["musica", "música", "pon", "reproduce", "play"]
    return any(k in pregunta.lower() for k in keywords)

def handle(pregunta: str) -> dict:
    query = pregunta.lower()

    for k in ["pon", "reproduce", "play", "música", "musica"]:
        query = query.replace(k, "")

    query = query.strip()

    if not query:
        query = "music"

    try:
        cmd = f"mpv $(yt-dlp -f bestaudio -g ytsearch1:{shlex.quote(query)})"
        subprocess.Popen(cmd, shell=True)

        return {
            "respuesta": f"🎵 Reproduciendo: {query}",
            "cerebro": "Music"
        }

    except Exception as e:
        return {
            "respuesta": f"Error al reproducir música: {str(e)}",
            "cerebro": "Music"
        }
