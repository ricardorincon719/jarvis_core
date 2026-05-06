import json
import subprocess

NAME = "termux_api"
VERSION = "1.0.0"
DESCRIPTION = "Diagnóstico y recuperación suave de Termux:API"
TRIGGERS = [
    "termux api", "termux:api", "api android", "api termux",
    "estado api", "probar api", "reparar api", "levantar api",
    "termux-volume", "termux-toast", "termux-torch"
]


def can_handle(prompt):
    p = prompt.lower().strip()
    return any(trigger in p for trigger in TRIGGERS)


def run_cmd(cmd, timeout=8):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "ok": result.returncode == 0,
            "code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "code": 127,
            "stdout": "",
            "stderr": f"Comando no encontrado: {cmd[0]}",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "code": 124,
            "stdout": "",
            "stderr": f"Timeout ejecutando: {' '.join(cmd)}",
        }
    except Exception as e:
        return {
            "ok": False,
            "code": 1,
            "stdout": "",
            "stderr": str(e),
        }


def start_api():
    return run_cmd(["termux-api-start"], timeout=8)


def toast_test():
    return run_cmd(["termux-toast", "PEARL Termux:API online"], timeout=8)


def volume_status():
    result = run_cmd(["termux-volume"], timeout=8)
    if not result["ok"]:
        return result

    try:
        result["streams"] = json.loads(result["stdout"])
    except Exception:
        result["streams"] = None

    return result


def battery_status():
    result = run_cmd(["termux-battery-status"], timeout=8)
    if not result["ok"]:
        return result

    try:
        result["battery"] = json.loads(result["stdout"])
    except Exception:
        result["battery"] = None

    return result


def soft_repair():
    steps = [
        ("force_stop", run_cmd(["am", "force-stop", "com.termux.api"], timeout=8)),
        ("open_app", run_cmd(["monkey", "-p", "com.termux.api", "1"], timeout=8)),
        ("start_api", start_api()),
        ("toast", toast_test()),
        ("volume", volume_status()),
    ]

    ok = any(name in {"toast", "volume"} and result["ok"] for name, result in steps)
    return ok, steps


def summarize_error(result):
    text = result.get("stderr") or result.get("stdout") or "sin detalle"
    if "process is bad" in text:
        return "Android marcó Termux:API como proceso fallido. Abre Termux:API o fuerza cierre desde Ajustes."
    if result.get("code") == 124:
        return "Termux:API no respondió antes del timeout."
    return text


def handle(prompt):
    p = prompt.lower().strip()

    if "reparar" in p or "revivir" in p:
        ok, steps = soft_repair()
        if ok:
            return {
                "respuesta": "Termux:API respondió después de la reparación suave.",
                "cerebro": NAME,
                "status": "ok",
                "steps": steps,
            }

        last_error = next((result for _, result in reversed(steps) if not result["ok"]), None)
        return {
            "respuesta": f"Termux:API sigue sin responder: {summarize_error(last_error or {})}",
            "cerebro": NAME,
            "status": "degraded",
            "steps": steps,
        }

    if "levantar" in p or "iniciar" in p or "start" in p:
        result = start_api()
        if result["ok"]:
            return {
                "respuesta": "Termux:API iniciado.",
                "cerebro": NAME,
                "status": "ok",
                "result": result,
            }
        return {
            "respuesta": f"No pude iniciar Termux:API: {summarize_error(result)}",
            "cerebro": NAME,
            "status": "degraded",
            "result": result,
        }

    if "volumen" in p or "termux-volume" in p:
        result = volume_status()
        if result["ok"]:
            return {
                "respuesta": "Termux:API responde para volumen.",
                "cerebro": NAME,
                "status": "ok",
                "result": result,
            }
        return {
            "respuesta": f"Termux:API no respondió para volumen: {summarize_error(result)}",
            "cerebro": NAME,
            "status": "degraded",
            "result": result,
        }

    if "bateria" in p or "batería" in p:
        result = battery_status()
        if result["ok"]:
            battery = result.get("battery") or {}
            percentage = battery.get("percentage", "?")
            status = battery.get("status", "unknown")
            return {
                "respuesta": f"Termux:API responde. Batería: {percentage}%, estado: {status}.",
                "cerebro": NAME,
                "status": "ok",
                "result": result,
            }
        return {
            "respuesta": f"Termux:API no respondió para batería: {summarize_error(result)}",
            "cerebro": NAME,
            "status": "degraded",
            "result": result,
        }

    start_result = start_api()
    toast_result = toast_test()
    volume_result = volume_status()

    if toast_result["ok"] or volume_result["ok"]:
        return {
            "respuesta": "Termux:API está respondiendo.",
            "cerebro": NAME,
            "status": "ok",
            "checks": {
                "start": start_result,
                "toast": toast_result,
                "volume": volume_result,
            },
        }

    return {
        "respuesta": f"Termux:API no responde: {summarize_error(volume_result)}",
        "cerebro": NAME,
        "status": "degraded",
        "checks": {
            "start": start_result,
            "toast": toast_result,
            "volume": volume_result,
        },
    }
