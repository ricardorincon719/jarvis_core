VERSION = "1.4.3"
DESCRIPTION = "Domótica local robusta para PEARL HOME"

TRIGGERS = [
    "luz", "lampara", "lámpara", "lectura", "relax", "noche", "normal",
    "calida", "cálida", "fria", "fría",
    "rojo", "roja", "verde", "azul",
    "cuarto", "apagar", "apaga", "encender", "enciende",
    "prender", "prende", "activar", "estado",
    "restaurar", "deshacer", "como estaba", "cómo estaba",
    "ultimo estado", "último estado"
]

import json
import unicodedata
from pathlib import Path

from branches.domotica.service import DomoticaService

domo = DomoticaService()
DEVICE_NAME = "lamp_quarto"

BASE_DIR = Path(__file__).resolve().parent.parent
LAST_BEFORE_OFF_FILE = BASE_DIR / "last_before_off.json"

SCENE_LECTURA = {"switch": True, "mode": "white", "brightness": 1000, "temp": 850}
SCENE_RELAX   = {"switch": True, "mode": "white", "brightness": 350, "temp": 150}
SCENE_NOCHE   = {"switch": True, "mode": "white", "brightness": 80, "temp": 60}
SCENE_NORMAL  = {"switch": True, "mode": "white", "brightness": 800, "temp": 650}

SCENE_FRIA    = {"switch": True, "mode": "white", "brightness": 700, "temp": 1000}
SCENE_CALIDA  = {"switch": True, "mode": "white", "brightness": 1000, "temp": 0}

SCENE_ROJO  = {"switch": True, "mode": "colour", "rgb": [255, 0, 0]}
SCENE_VERDE = {"switch": True, "mode": "colour", "rgb": [0, 255, 0]}
SCENE_AZUL  = {"switch": True, "mode": "colour", "rgb": [0, 0, 255]}


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(text.split())


def has_any(text: str, words) -> bool:
    return any(w in text for w in words)


def is_light_target(text: str) -> bool:
    return has_any(text, ["luz", "lampara", "cuarto", "foco", "bombilla"])


def is_turn_on_intent(text: str) -> bool:
    return has_any(text, ["encender", "enciende", "prender", "prende", "activar"])


def is_turn_off_intent(text: str) -> bool:
    return has_any(text, ["apagar", "apaga"])


def can_handle(pregunta):
    p = normalize_text(pregunta)
    return any(normalize_text(t) in p for t in TRIGGERS)


def get_current_scene_snapshot():
    status = domo.status(DEVICE_NAME)
    print(f"[Domotica] Status crudo para snapshot: {status}")

    inner_status = status.get("status") or {}
    dps_raw = inner_status.get("dps") or {}
    dps = {str(k): v for k, v in dps_raw.items()}

    scene = {
        "switch": bool(dps.get("20", False)),
        "mode": dps.get("21", "white"),
    }

    if scene["mode"] == "white":
        scene["brightness"] = int(dps.get("22", 500))
        scene["temp"] = int(dps.get("23", 500))
    elif scene["mode"] == "colour":
        scene["raw_colour"] = dps.get("24")
        scene["color"] = dps.get("24")

    print(f"[Domotica] Snapshot actual: {scene}")
    return scene

def save_last_before_off():
    scene = get_current_scene_snapshot()
    LAST_BEFORE_OFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_BEFORE_OFF_FILE, "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)
    print(f"[Domotica] Guardado last_before_off en {LAST_BEFORE_OFF_FILE}: {scene}")


def load_last_before_off():
    if not LAST_BEFORE_OFF_FILE.exists():
        raise ValueError(f"No existe backup previo al apagado: {LAST_BEFORE_OFF_FILE}")

    with open(LAST_BEFORE_OFF_FILE, "r", encoding="utf-8") as f:
        scene = json.load(f)

    scene["switch"] = True
    print(f"[Domotica] Cargado last_before_off desde {LAST_BEFORE_OFF_FILE}: {scene}")
    return scene


def apply_scene(scene: dict):
    print(f"[Domotica] Aplicando escena: {scene}")
    return domo.apply_scene(DEVICE_NAME, scene)


def handle(pregunta):
    p = normalize_text(pregunta)

    try:
        if has_any(p, ["deshacer", "como estaba", "ultimo estado"]):
            r = apply_scene(SCENE_NORMAL)
            return {
                "respuesta": f"Luz vuelta al modo normal ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "restaurar" in p:
            previous_scene = load_last_before_off()
            r = apply_scene(previous_scene)
            return {
                "respuesta": f"Último estado antes de apagar restaurado ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "lectura" in p and is_light_target(p):
            r = apply_scene(SCENE_LECTURA)
            return {
                "respuesta": f"Luz en modo lectura ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "relax" in p and is_light_target(p):
            r = apply_scene(SCENE_RELAX)
            return {
                "respuesta": f"Luz en modo relax ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "noche" in p and is_light_target(p):
            r = apply_scene(SCENE_NOCHE)
            return {
                "respuesta": f"Luz en modo noche ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "normal" in p and is_light_target(p):
            r = apply_scene(SCENE_NORMAL)
            return {
                "respuesta": f"Luz en modo normal ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "fria" in p and is_light_target(p):
            r = apply_scene(SCENE_FRIA)
            return {
                "respuesta": f"Luz fría activada ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "calida" in p and is_light_target(p):
            r = apply_scene(SCENE_CALIDA)
            return {
                "respuesta": f"Luz cálida activada ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if ("rojo" in p or "roja" in p) and is_light_target(p):
            r = apply_scene(SCENE_ROJO)
            return {
                "respuesta": f"Luz roja activada ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "verde" in p and is_light_target(p):
            r = apply_scene(SCENE_VERDE)
            return {
                "respuesta": f"Luz verde activada ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "azul" in p and is_light_target(p):
            r = apply_scene(SCENE_AZUL)
            return {
                "respuesta": f"Luz azul activada ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if is_turn_off_intent(p) and is_light_target(p):
            save_last_before_off()
            r = domo.turn_off(DEVICE_NAME)
            return {
                "respuesta": f"Luz apagada ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if is_turn_on_intent(p) and is_light_target(p):
            r = domo.turn_on(DEVICE_NAME)
            return {
                "respuesta": f"Luz encendida ({r['ip']})",
                "cerebro": "Domotica",
                "debug": r
            }

        if "estado luz" in p or "estado de la luz" in p or ("estado" in p and is_light_target(p)):
            r = domo.status(DEVICE_NAME)
            return {
                "respuesta": f"Luz disponible en IP {r['ip']}.",
                "cerebro": "Domotica",
                "debug": r
            }

        return {
            "respuesta": f"Comando domótico no reconocido: '{pregunta}'",
            "cerebro": "Domotica",
            "debug": {"normalized": p}
        }

    except Exception as e:
        return {
            "respuesta": f"Error en domótica: {e}",
            "cerebro": "Domotica"
        }
