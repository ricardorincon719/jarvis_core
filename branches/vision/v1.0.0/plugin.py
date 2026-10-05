"""
Plugin VISION - La cámara de escritorio de Jarvis (servicio PEARL Vision :5007)

Solo consulta al servicio local; nunca guarda imágenes. La descripción por un
modelo remoto se pide únicamente cuando la persona pregunta cómo se ve.
"""

import os
import re

import requests

from router import contains_phrase, normalize_text

NAME = "vision"
VERSION = "v1.0.0"
DESCRIPTION = "Cámara de escritorio: cómo te ves, cuánto llevas frente a la laptop, pausar la cámara"
TRIGGERS = ["mirame", "como me veo", "que ves", "como he estado", "deja de mirarme", "camara"]

VISION_URL = os.environ.get("PEARL_VISION_URL", "http://127.0.0.1:5007")
LOOK_TIMEOUT = 60

LEADING_NAME_RE = re.compile(r"^(?:oye\s+)?(?:jarvis|jinnex|jinnez|ginnex|ginnes)\s+")

# Frases que bastan con aparecer en cualquier parte.
LOOK_PHRASES = (
    "como me veo", "como luzco", "mirame", "mira me", "que ves", "que estas viendo",
    "me ves", "describeme", "observame",
)
SUMMARY_PHRASES = (
    "como he estado", "cuanto llevo frente", "cuanto llevo en la laptop",
    "cuanto llevo sentado", "resumen de la camara",
)
PAUSE_PHRASES = (
    "deja de mirarme", "no me mires", "pausa la camara", "apaga la camara",
    "desactiva la camara", "deten la camara",
)
RESUME_PHRASES = (
    "vuelve a mirarme", "puedes mirarme", "reanuda la camara", "activa la camara",
    "enciende la camara", "prende la camara",
)
# Frases ambiguas: solo cuentan si son toda la petición.
LOOK_EXACT = {"como estoy", "como me ves", "como estoy hoy", "mira"}


def _clean(prompt: str) -> str:
    return LEADING_NAME_RE.sub("", normalize_text(prompt or ""))


def detect_intent(prompt: str):
    text = _clean(prompt)
    if any(contains_phrase(text, p) for p in PAUSE_PHRASES):
        return "pause"
    if any(contains_phrase(text, p) for p in RESUME_PHRASES):
        return "resume"
    if any(contains_phrase(text, p) for p in SUMMARY_PHRASES):
        return "summary"
    if text in LOOK_EXACT or any(contains_phrase(text, p) for p in LOOK_PHRASES):
        return "look"
    return None


def can_handle(prompt):
    return detect_intent(prompt) is not None


def _reply(text, ok=True, **extra):
    return {"respuesta": text, "cerebro": NAME, "ok": ok, **extra}


def _unavailable(exc):
    return _reply(
        "No puedo acceder a la cámara en este momento, señor. "
        "El servicio de visión no responde.",
        ok=False,
        debug={"error": str(exc)},
    )


def _look():
    response = requests.post(f"{VISION_URL}/look", json={"describe": True}, timeout=LOOK_TIMEOUT)
    data = response.json()
    if response.status_code == 409:
        return _reply(
            "La cámara está ocupada por otro programa, señor. Ciérrelo y vuelvo a mirar.",
            ok=False,
        )
    if data.get("status") == "camera_failed":
        return _reply(
            "La cámara no responde, señor. Desconéctela unos segundos y vuelva a "
            "conectarla en modo cámara de PC.",
            ok=False,
            debug={"error": data.get("error")},
        )
    if response.status_code != 200:
        return _reply(f"No pude mirar, señor: {data.get('error', 'error desconocido')}.", ok=False)

    signals = data.get("signals") or {}
    if not signals.get("present"):
        return _reply("No lo veo frente a la cámara, señor.", signals=signals)
    if signals.get("owner") is False:
        return _reply(
            "Veo a alguien frente a la cámara, pero no lo reconozco como usted, señor.",
            signals=signals,
        )

    description = data.get("description")
    if description:
        return _reply(description, signals=signals)

    # Sin descripción remota: respondemos con las señales locales.
    light = {
        "oscuro": "con muy poca luz",
        "muy_brillante": "con demasiada luz",
    }.get(signals.get("light"), "con buena luz")
    return _reply(
        f"Lo veo frente a la laptop, {light}. "
        "No pude obtener una descripción más detallada en este momento.",
        signals=signals,
        debug={"description_error": data.get("description_error")},
    )


def _duration(minutes):
    hours, rest = divmod(int(minutes), 60)
    if not hours:
        return f"{rest} minutos"
    text = f"{hours} hora{'s' if hours != 1 else ''}"
    return text + (f" y {rest} minutos" if rest else "")


def _summary():
    response = requests.get(f"{VISION_URL}/summary", params={"hours": 3}, timeout=10)
    summary = (response.json() or {}).get("summary") or {}
    checks = summary.get("checks", 0)
    if not checks:
        return _reply(
            "Aún no tengo observaciones de las últimas 3 horas, señor.",
            summary=summary,
        )

    parts = []
    session = summary.get("current_session_minutes", 0)
    if session:
        parts.append(f"Lleva unos {_duration(session)} frente a la laptop sin ausentarse")
    else:
        parts.append("En la última observación no estaba frente a la laptop")

    present = summary.get("present_checks", 0)
    parts.append(f"en las últimas 3 horas lo vi en {present} de {checks} chequeos")
    dark = summary.get("dark_checks", 0)
    if dark:
        parts.append(f"{dark} de ellos con muy poca luz")
    if not summary.get("monitor_enabled", True):
        parts.append("los chequeos periódicos están en pausa")
    return _reply(", ".join(parts) + ", señor.", summary=summary)


def _monitor(enabled):
    response = requests.post(f"{VISION_URL}/monitor", json={"enabled": enabled}, timeout=10)
    response.raise_for_status()
    if enabled:
        return _reply("Entendido, señor. Vuelvo a revisar cómo está cada cierto tiempo.")
    return _reply("Entendido, señor. Dejo de mirarlo hasta que me lo pida.")


def handle(prompt):
    intent = detect_intent(prompt) or "look"
    try:
        if intent == "pause":
            return _monitor(False)
        if intent == "resume":
            return _monitor(True)
        if intent == "summary":
            return _summary()
        return _look()
    except (requests.RequestException, ValueError) as exc:
        return _unavailable(exc)


def status():
    try:
        return requests.get(f"{VISION_URL}/health", timeout=3).json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unavailable", "error": str(exc)}
