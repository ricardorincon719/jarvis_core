"""
Plugin HARDWARE - Control real de hardware
"""

import subprocess
import json

NAME = "hardware"
VERSION = "v1.2.0"
DESCRIPTION = "Control de hardware local del celular (linterna, batería, vibración, biometría)"
TRIGGERS = [
    "linterna", "batería", "bateria", "reporte", "sistemas",
    "vibrar", "huella", "biometría", "biometria", "energía"
]


def can_handle(prompt):
    prompt_lower = prompt.lower()
    return any(keyword in prompt_lower for keyword in TRIGGERS)


def build_plan(prompt):
    prompt_lower = prompt.lower()
    if "linterna" in prompt_lower:
        if any(x in prompt_lower for x in ["encender", "enciende", "prender", "prende", "activar", "activa", "on"]):
            action_type = "torch_on"
        else:
            action_type = "torch_off"
        return {"agent": NAME, "intent": action_type, "actions": [{"type": action_type}]}

    if "batería" in prompt_lower or "bateria" in prompt_lower or "energía" in prompt_lower:
        return {"agent": NAME, "intent": "battery_status", "actions": [{"type": "battery_status"}]}

    if "vibrar" in prompt_lower:
        return {"agent": NAME, "intent": "vibrate", "actions": [{"type": "vibrate", "duration_ms": 1000}]}

    if "huella" in prompt_lower or "biometría" in prompt_lower or "biometria" in prompt_lower:
        return {"agent": NAME, "intent": "fingerprint", "actions": [{"type": "fingerprint"}]}

    return {"agent": NAME, "intent": "unknown", "actions": []}


def execute_confirmed_plan(plan, prompt):
    actions = plan.get("actions") or []
    if len(actions) != 1 or not isinstance(actions[0], dict):
        return {"respuesta": "Comando no reconocido.", "cerebro": NAME}

    action = actions[0]
    action_type = action.get("type")
    if action_type not in {"torch_on", "torch_off", "battery_status", "vibrate", "fingerprint"}:
        raise ValueError(f"Accion de hardware no permitida: {action_type}")

    if action_type in {"torch_on", "torch_off"}:
        enabled = action_type == "torch_on"
        subprocess.run(["termux-torch", "on" if enabled else "off"])
        return {
            "respuesta": (
                "Sistemas de iluminación activados, señor."
                if enabled else "Sistemas de iluminación desactivados, señor."
            ),
            "cerebro": NAME,
            "ok": True,
        }

    if action_type == "battery_status":
        porcentaje = 0
        estado_texto = "desconocido"

        try:
            result = subprocess.run(
                ["termux-battery-status"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout:
                bat = json.loads(result.stdout)
                porcentaje = bat.get("percentage", 0)
                estado = bat.get("status", "unknown")
                estado_texto = (
                    "cargando" if estado == "CHARGING"
                    else "descargando" if estado == "DISCHARGING"
                    else "conectado"
                )
            else:
                raise Exception("termux-battery-status no respondió")
        except Exception:
            try:
                import re
                result = subprocess.run(
                    ["/system/bin/dumpsys", "battery"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                level_match = re.search(r"level:\s+(\d+)", result.stdout)
                status_match = re.search(r"status:\s+(\d+)", result.stdout)

                if level_match:
                    porcentaje = int(level_match.group(1))

                if status_match:
                    status_code = int(status_match.group(1))
                    if status_code == 2:
                        estado_texto = "cargando"
                    elif status_code == 3:
                        estado_texto = "descargando"
                    elif status_code == 5:
                        estado_texto = "completa"
                    else:
                        estado_texto = "conectado"
            except Exception as e:
                return {
                    "respuesta": f"Error obteniendo batería: {e}",
                    "cerebro": NAME
                }

        return {
            "respuesta": f"Energía al {porcentaje}%. Estado: {estado_texto}.",
            "cerebro": NAME
        }

    if action_type == "vibrate":
        duration = max(100, min(5000, int(action.get("duration_ms") or 1000)))
        subprocess.run(["termux-vibrate", "-d", str(duration)])
        return {
            "respuesta": "Alerta táctil activada.",
            "cerebro": NAME,
            "ok": True,
        }

    if action_type == "fingerprint":
        try:
            result = subprocess.run(
                ["termux-fingerprint"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if "AUTH_RESULT_SUCCESS" in result.stdout:
                return {
                    "respuesta": "Identificación biométrica exitosa. Bienvenido.",
                    "cerebro": NAME
                }
            return {
                "respuesta": "Identificación fallida.",
                "cerebro": NAME
            }
        except Exception:
            return {
                "respuesta": "Sensor de huella no responde.",
                "cerebro": NAME
            }

    raise ValueError(f"Accion de hardware no soportada: {action_type}")


def handle(prompt):
    return execute_confirmed_plan(build_plan(prompt), prompt)
