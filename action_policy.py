"""Politica central de autorizacion para planes de accion de PEARL."""

import re
import unicodedata


LEVEL_RESPOND_ONLY = 0
LEVEL_SAFE = 1
LEVEL_CONFIRM = 2
LEVEL_BLOCKED = 3


ACTION_LEVELS = {
    "domotica": {
        "status": LEVEL_SAFE,
        "memory_summary": LEVEL_SAFE,
        "list_scenes": LEVEL_SAFE,
        "suggest_scene": LEVEL_SAFE,
        "list_devices": LEVEL_SAFE,
        "list_device_candidates": LEVEL_SAFE,
        "remember_note": LEVEL_SAFE,
        "turn_on": LEVEL_SAFE,
        "turn_off": LEVEL_SAFE,
        "apply_scene": LEVEL_SAFE,
        "restore_before_off": LEVEL_SAFE,
        "restore_previous_state": LEVEL_SAFE,
        "apply_learned_scene": LEVEL_CONFIRM,
        "approve_scene": LEVEL_CONFIRM,
        "reject_scene": LEVEL_CONFIRM,
        "discover_devices": LEVEL_CONFIRM,
        "activate_automation": LEVEL_CONFIRM,
    },
    "music": {
        "status": LEVEL_SAFE,
        "pause": LEVEL_SAFE,
        "play": LEVEL_CONFIRM,
        "resume": LEVEL_CONFIRM,
        "stop": LEVEL_CONFIRM,
        "next": LEVEL_CONFIRM,
        "previous": LEVEL_CONFIRM,
    },
    "music_local": {
        "status": LEVEL_SAFE,
        "pause": LEVEL_SAFE,
        "play": LEVEL_CONFIRM,
        "resume": LEVEL_CONFIRM,
        "stop": LEVEL_CONFIRM,
        "next": LEVEL_CONFIRM,
        "previous": LEVEL_CONFIRM,
        "volume_up": LEVEL_CONFIRM,
        "volume_down": LEVEL_CONFIRM,
    },
    "hardware": {
        "battery_status": LEVEL_SAFE,
        "torch_on": LEVEL_SAFE,
        "torch_off": LEVEL_SAFE,
        "vibrate": LEVEL_CONFIRM,
        "fingerprint": LEVEL_CONFIRM,
    },
    "communication": {
        "send_message": LEVEL_CONFIRM,
    },
    "network": {
        "open_ngrok_tunnel": LEVEL_CONFIRM,
    },
    "automation": {
        "activate_automation": LEVEL_CONFIRM,
    },
}


BLOCKED_ACTIONS = {
    "delete_file",
    "delete_directory",
    "expose_port",
    "modify_token",
    "rotate_token",
    "write_secret",
    "modify_sensitive_config",
    "execute_shell",
}


def classify_action(plugin_name: str, action: dict) -> int:
    if not isinstance(action, dict):
        return LEVEL_BLOCKED
    action_type = str(action.get("type") or "").strip()
    if not action_type or action_type in BLOCKED_ACTIONS:
        return LEVEL_BLOCKED
    return ACTION_LEVELS.get(plugin_name, {}).get(action_type, LEVEL_BLOCKED)


def classify_plan(plugin_name: str, plan: dict) -> int:
    if not isinstance(plan, dict):
        return LEVEL_BLOCKED
    actions = plan.get("actions") or []
    if not actions:
        return LEVEL_RESPOND_ONLY
    return max(classify_action(plugin_name, action) for action in actions)


def blocked_prompt_reason(prompt: str):
    """Detecta solicitudes sensibles antes de enviarlas a un plugin o modelo."""
    text = _normalize(prompt)

    destructive = r"\b(?:borra|borrar|elimina|eliminar|destruye|destruir)\b"
    storage = r"\b(?:archivo|archivos|carpeta|carpetas|directorio|directorios)\b"
    if (re.search(destructive, text) and re.search(storage, text)):
        return "borrado_de_archivos"

    port_action = r"\b(?:expone|exponer|publica|publicar|habilita|habilitar)\b"
    if "ngrok" not in text and re.search(port_action, text) and re.search(r"\bpuertos?\b", text):
        return "exposicion_de_puertos"

    secret_action = r"\b(?:toca|tocar|modifica|modificar|cambia|cambiar|borra|borrar|rota|rotar)\b"
    secrets = r"\b(?:token|tokens|secreto|secretos|credencial|credenciales|clave api|api key)\b"
    if re.search(secret_action, text) and re.search(secrets, text):
        return "modificacion_de_secretos"

    sensitive_config = r"(?:configuracion sensible|credenciales|archivo env|\.env|secrets?)"
    if re.search(secret_action, text) and re.search(sensitive_config, text):
        return "configuracion_sensible"

    return None


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.split())
