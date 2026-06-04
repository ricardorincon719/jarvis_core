#!/usr/bin/env python3
"""
JARVIS CORE - Sistema de Plugins Modular
El core solo orquesta, nunca ejecuta comandos peligrosos.
"""

import json
import importlib
import hashlib
import hmac
import ipaddress
import os
import re
import socket
import time
from pathlib import Path
import requests
from branches.scene_memory import SharedSceneMemory
from device_sessions import DeviceSessionStore
from router import is_system_status_request, normalize_text, route_query, update_context
from flask import Flask, Response, render_template, request, jsonify, stream_with_context
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ========== CONFIGURACIÓN ==========
BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path: Path = BASE_DIR / ".env"):
    """Carga .env simple sin agregar dependencia externa."""
    if not path.exists():
        return

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


SECRET_TOKEN = os.getenv("JARVIS_SECRET_TOKEN", "jarvis_local_123")
CORE_HOST = os.getenv("JARVIS_CORE_HOST", "0.0.0.0")
CORE_PORT = int(os.getenv("JARVIS_CORE_PORT", "5004"))
CORE_DEBUG = os.getenv("JARVIS_CORE_DEBUG", "false").lower() in {"1", "true", "yes"}
CORE_DEV_MODE = os.getenv("JARVIS_CORE_DEV_MODE", "false").lower() in {"1", "true", "yes"}
PEARL_PRODUCT = os.getenv("PEARL_PRODUCT", "PEARL Lite").strip() or "PEARL Lite"
PEARL_EDITION = os.getenv("PEARL_EDITION", "lite").strip().lower() or "lite"
PEARL_VERSION = os.getenv("PEARL_VERSION", "0.7.0-beta.1").strip() or "0.7.0-beta.1"
PEARL_API_VERSION = "v1"
SESSION_TTL_SECONDS = int(os.getenv("JARVIS_SESSION_TTL_SECONDS", "2592000"))
DEVICE_SESSION_MAX = int(os.getenv("PEARL_DEVICE_SESSION_MAX", "100"))
DEVICE_SESSIONS_FILE = Path(os.getenv("PEARL_DEVICE_SESSIONS_FILE", str(Path.home() / ".local/share/pearl-home/device_sessions.json")))
AUTH_MAX_ATTEMPTS = int(os.getenv("JARVIS_AUTH_MAX_ATTEMPTS", "5"))
AUTH_LOCKOUT_SECONDS = int(os.getenv("JARVIS_AUTH_LOCKOUT_SECONDS", "300"))
BRANCHES_DIR = Path(os.getenv("JARVIS_BRANCHES_DIR", str(BASE_DIR / "branches")))
MANIFEST_FILE = Path(os.getenv("JARVIS_MANIFEST_FILE", str(BASE_DIR / "plugin_manifest.json")))
AI_PROVIDER = os.getenv("JARVIS_AI_PROVIDER", "local").strip().lower() or "local"
LOCAL_AI_URL = os.getenv("JARVIS_LOCAL_AI_URL", os.getenv("JARVIS_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
LOCAL_AI_MODEL = os.getenv("JARVIS_LOCAL_AI_MODEL", os.getenv("JARVIS_OLLAMA_MODEL", "qwen2.5:0.5b")).strip()
CLOUD_AI_ENABLED = env_bool("JARVIS_CLOUD_AI_ENABLED", "false")
CLOUD_AI_PROVIDER = os.getenv("JARVIS_CLOUD_AI_PROVIDER", "").strip()
CLOUD_AI_HEALTH_URL = os.getenv("JARVIS_CLOUD_AI_HEALTH_URL", "").strip()
AI_STATUS_TIMEOUT = env_float("JARVIS_AI_STATUS_TIMEOUT", "2")
plugins = {}
plugin_errors = {}
shared_scene_memory = SharedSceneMemory()
device_session_store = DeviceSessionStore(DEVICE_SESSIONS_FILE, SESSION_TTL_SECONDS, DEVICE_SESSION_MAX)
auth_failures = {}

COMPOUND_CONNECTOR_RE = re.compile(
    r"\s+(?:y|e|tambien|también|ademas|además|luego|despues|después)\s+"
    r"(?=(?:prende|enciende|apaga|apagar|encender|reproduce|reproducir|pon|play|"
    r"pausa|reanuda|continua|activa|activar|restaurar|deshacer|estado|luz|"
    r"lampara|lámpara|domotica|domótica|musica|música)\b)",
    re.IGNORECASE,
)


def product_identity():
    return {
        "name": PEARL_PRODUCT,
        "edition": PEARL_EDITION,
        "version": PEARL_VERSION,
        "api_version": PEARL_API_VERSION,
    }


def running_in_termux() -> bool:
    return Path("/data/data/com.termux/files/home").exists()


def guard_core_execution():
    """Evita arrancar el core móvil como servicio accidental en laptop."""
    if running_in_termux() or CORE_DEV_MODE:
        return

    print("JARVIS CORE no se arrancó.")
    print("Este repo es la copia del core móvil. En laptop úsalo para revisar, editar y probar.")
    print("Para prueba explícita: JARVIS_CORE_DEV_MODE=true .venv/bin/python core.py")
    raise SystemExit(2)


# ========== SEGURIDAD ==========
def es_ip_local(ip: str) -> bool:
    """Acepta loopback, privadas y red compartida CGNAT."""
    try:
        ip_obj = ipaddress.ip_address(ip)

        if ip_obj.is_loopback or ip_obj.is_private:
            return True

        cgnat = ipaddress.ip_network("100.64.0.0/10")
        if ip_obj in cgnat:
            return True

        return False
    except ValueError:
        return False


def token_valido(req) -> bool:
    """Valida header Authorization con formato Bearer."""
    token = bearer_token(req)
    if not token:
        return False
    if hmac.compare_digest(token, SECRET_TOKEN):
        return True
    return session_token_valido(token)


def bearer_token(req) -> str:
    auth = req.headers.get("Authorization", "").strip()
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return ""
    return auth[len(prefix):].strip()


def cleanup_expired_sessions():
    return device_session_store.prune()


def issue_session_token(device_id: str = "", device_name: str = "") -> str:
    return device_session_store.issue(device_id=device_id, device_name=device_name)


def session_token_valido(token: str) -> bool:
    return device_session_store.validate(token) is not None


def auth_client_key(req) -> str:
    return (req.remote_addr or "unknown").strip() or "unknown"


def auth_lockout_response(req):
    key = auth_client_key(req)
    entry = auth_failures.get(key)
    if not entry:
        return None

    locked_until = entry.get("locked_until", 0)
    now = time.time()
    if locked_until > now:
        retry_after = max(1, int(locked_until - now))
        return jsonify({
            "success": False,
            "message": "Demasiados intentos. Intenta de nuevo más tarde.",
            "retry_after": retry_after,
        }), 429

    if locked_until:
        auth_failures.pop(key, None)
    return None


def record_auth_failure(req):
    key = auth_client_key(req)
    entry = auth_failures.setdefault(key, {"count": 0, "locked_until": 0})
    entry["count"] += 1
    if entry["count"] >= AUTH_MAX_ATTEMPTS:
        entry["locked_until"] = time.time() + AUTH_LOCKOUT_SECONDS


def clear_auth_failures(req):
    auth_failures.pop(auth_client_key(req), None)

def get_current_lan_ip() -> str:
    """Obtiene la IP LAN actual del dispositivo de forma dinámica."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def acceso_local_autorizado(req):
    """
    Devuelve None si está autorizado.
    Devuelve respuesta JSON de error si falla token o IP.
    """
    ip = (req.remote_addr or "").strip()

    if not token_valido(req):
        return jsonify({"error": "Unauthorized"}), 403

    if not es_ip_local(ip):
        return jsonify({"error": "Forbidden"}), 403

    return None


def acceso_ip_local(req):
    ip = (req.remote_addr or "").strip()
    if not es_ip_local(ip):
        return jsonify({"error": "Forbidden"}), 403
    return None


def json_object_or_error(req):
    data = req.get_json(silent=True)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, (jsonify({"error": "invalid_json_object"}), 400)
    return data, None


# ========== VERIFICACIÓN DE INTEGRIDAD ==========
def verify_plugin_integrity(plugin_path: Path) -> bool:
    """Verifica hash de los archivos del plugin."""
    integrity_file = plugin_path / "integrity.json"
    if not integrity_file.exists():
        print("   ⚠️ Sin archivo integrity.json")
        return True  # modo desarrollo

    with open(integrity_file, "r", encoding="utf-8") as f:
        expected = json.load(f)

    for file_name, expected_hash in expected.items():
        file_path = plugin_path / file_name
        if not file_path.exists():
            print(f"   ❌ Integridad fallida: falta {file_name}")
            return False

        with open(file_path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        if actual_hash != expected_hash:
            print(f"   ❌ Integridad fallida: {file_name}")
            return False

    return True


# ========== CARGA DE PLUGINS ==========
def load_plugins():
    """Escanea branches/ y carga todos los plugins."""
    plugins.clear()
    plugin_errors.clear()

    if not BRANCHES_DIR.exists():
        BRANCHES_DIR.mkdir(parents=True)
        print("📁 Carpeta branches/ creada")
        return

    print("\n🔍 Escaneando plugins...")

    for branch_name in BRANCHES_DIR.iterdir():
        if not branch_name.is_dir() or branch_name.name.startswith("_"):
            continue

        plugin_path = branch_name / "current"
        if not plugin_path.exists():
            continue

        try:
            if not verify_plugin_integrity(plugin_path):
                print(f"   ❌ {branch_name.name}: integridad fallida, omitido")
                plugin_errors[branch_name.name] = "integridad fallida"
                continue

            module = importlib.import_module(f"branches.{branch_name.name}.current.plugin")

            if hasattr(module, "handle"):
                plugins[branch_name.name] = {
                    "module": module,
                    "version": getattr(module, "VERSION", "v0.0.0"),
                    "description": getattr(module, "DESCRIPTION", "Sin descripción"),
                    "triggers": getattr(module, "TRIGGERS", []),
                }
                print(f"   ✅ {branch_name.name} {plugins[branch_name.name]['version']}")
            else:
                print(f"   ⚠️ {branch_name.name}: falta función handle()")
                plugin_errors[branch_name.name] = "falta función handle()"

        except Exception as e:
            print(f"   ❌ {branch_name.name}: error al cargar - {e}")
            plugin_errors[branch_name.name] = str(e)

    print(f"\n📊 Total plugins cargados: {len(plugins)}")


def plugin_domain(plugin_name: str) -> str:
    if plugin_name in {"music", "music_local"}:
        return "music"
    return plugin_name


def split_compound_prompt(prompt: str):
    parts = [
        part.strip(" ,.;")
        for part in COMPOUND_CONNECTOR_RE.split(prompt or "")
        if part.strip(" ,.;")
    ]
    return parts if len(parts) > 1 else []


def build_compound_dispatch(prompt: str, available_plugins):
    parts = split_compound_prompt(prompt)
    if len(parts) < 2:
        return []

    dispatch = []
    domains = set()

    for part in parts:
        plugin_name = route_query(part, available_plugins)
        domain = plugin_domain(plugin_name)

        if plugin_name not in plugins:
            return []
        if domain not in {"music", "domotica"}:
            return []

        dispatch.append({
            "prompt": part,
            "plugin": plugin_name,
            "domain": domain,
        })
        domains.add(domain)

    if len(dispatch) < 2 or len(domains) < 2:
        return []

    return dispatch


def execute_plugin(plugin_name: str, prompt: str):
    plugin_info = plugins[plugin_name]
    module = plugin_info["module"]

    response = module.handle(prompt)

    if not isinstance(response, dict):
        response = {"respuesta": str(response), "cerebro": plugin_name}

    response["plugin"] = plugin_name
    response["version"] = plugin_info["version"]
    update_context(plugin_name, prompt)
    return response


def build_core_status_response(prompt: str):
    scene_summary = shared_scene_memory.summary()
    loaded_plugins = sorted(plugins.keys())
    error_names = sorted(plugin_errors.keys())

    parts = [
        "Core online",
        f"plugins cargados: {len(loaded_plugins)}",
    ]
    if loaded_plugins:
        parts.append("disponibles: " + ", ".join(loaded_plugins))
    if error_names:
        parts.append("errores de plugin: " + ", ".join(error_names))
    else:
        parts.append("sin errores de plugin")

    candidate_scenes = scene_summary.get("candidate_scenes")
    approved_scenes = scene_summary.get("approved_scenes")
    if candidate_scenes is not None and approved_scenes is not None:
        parts.append(f"escenas: {candidate_scenes} candidatas, {approved_scenes} aprobadas")

    update_context("core_health", prompt)
    return {
        "respuesta": ". ".join(parts) + ".",
        "cerebro": "Core",
        "plugin": "core_health",
        "status": "online",
        "product": product_identity(),
        "plugins": loaded_plugins,
        "versions": {name: info["version"] for name, info in plugins.items()},
        "plugin_errors": plugin_errors,
        "scene_memory": scene_summary,
    }


def ollama_model_names(payload):
    names = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if name:
            names.append(str(name))
    return names


def model_name_matches(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return candidate == expected or candidate.split(":", 1)[0] == expected.split(":", 1)[0]


def check_local_ai_status():
    enabled = "local_ia" in plugins
    status = {
        "enabled": enabled,
        "url": LOCAL_AI_URL,
        "model": LOCAL_AI_MODEL,
        "connected": False,
        "model_available": False,
        "model_loaded": False,
        "status": "disabled" if not enabled else "disconnected",
        "error": None,
    }

    if not enabled:
        status["error"] = "plugin local_ia no cargado"
        return status

    try:
        tags = requests.get(f"{LOCAL_AI_URL}/api/tags", timeout=AI_STATUS_TIMEOUT)
        if tags.status_code != 200:
            status["error"] = f"ollama_http_{tags.status_code}"
            return status

        status["connected"] = True
        available_models = ollama_model_names(tags.json())
        status["model_available"] = any(
            model_name_matches(name, LOCAL_AI_MODEL)
            for name in available_models
        )

        try:
            running = requests.get(f"{LOCAL_AI_URL}/api/ps", timeout=AI_STATUS_TIMEOUT)
            if running.status_code == 200:
                running_models = ollama_model_names(running.json())
                status["model_loaded"] = any(
                    model_name_matches(name, LOCAL_AI_MODEL)
                    for name in running_models
                )
        except requests.RequestException:
            status["model_loaded"] = False

        if status["model_loaded"]:
            status["status"] = "loaded"
        elif status["model_available"]:
            status["status"] = "available"
        else:
            status["status"] = "missing_model"

        return status
    except Exception as e:
        status["error"] = str(e)
        return status


def check_cloud_ai_status():
    status = {
        "enabled": CLOUD_AI_ENABLED,
        "provider": CLOUD_AI_PROVIDER or None,
        "health_url": CLOUD_AI_HEALTH_URL or None,
        "connected": False,
        "configured": bool(CLOUD_AI_PROVIDER or CLOUD_AI_HEALTH_URL),
        "status": "disabled",
        "error": None,
    }

    if not CLOUD_AI_ENABLED:
        return status

    if not CLOUD_AI_HEALTH_URL:
        status["status"] = "configured"
        return status

    try:
        response = requests.get(CLOUD_AI_HEALTH_URL, timeout=AI_STATUS_TIMEOUT)
        status["connected"] = 200 <= response.status_code < 400
        status["status"] = "connected" if status["connected"] else "error"
        if not status["connected"]:
            status["error"] = f"http_{response.status_code}"
        return status
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
        return status


def build_ai_status_response():
    local = check_local_ai_status()
    cloud = check_cloud_ai_status()
    provider = AI_PROVIDER if AI_PROVIDER in {"local", "cloud", "auto"} else "local"

    if provider == "cloud":
        active = "cloud"
        connected = cloud["connected"]
    elif provider == "auto" and cloud["connected"]:
        active = "cloud"
        connected = True
    else:
        active = "local"
        connected = local["connected"]

    return {
        "success": True,
        "provider": provider,
        "active": active,
        "connected": connected,
        "local": local,
        "cloud": cloud,
        "last_check": int(time.time()),
    }


def execute_compound_dispatch(dispatch, original_prompt=None):
    steps = []
    ok = True

    for item in dispatch:
        plugin_name = item["plugin"]
        prompt = item["prompt"]

        try:
            response = execute_plugin(plugin_name, prompt)
            response["compound_prompt"] = prompt
            steps.append(response)
        except Exception as e:
            ok = False
            print(f"   ❌ Error en paso compuesto {plugin_name}: {e}")
            steps.append({
                "respuesta": f"Error ejecutando {plugin_name}: {str(e)}",
                "cerebro": "Core",
                "plugin": plugin_name,
                "compound_prompt": prompt,
                "error": str(e),
            })

    respuestas = [
        str(step.get("respuesta") or step.get("message") or step.get("plugin"))
        for step in steps
    ]

    def step_ok(step):
        if step.get("error"):
            return False
        if "ok" in step and not bool(step.get("ok")):
            return False
        nested_status = step.get("status")
        if isinstance(nested_status, dict) and nested_status.get("status") == "error":
            return False
        return True

    result = {
        "respuesta": " | ".join(respuestas),
        "cerebro": "Core",
        "plugin": "compound",
        "compound": True,
        "ok": ok and all(step_ok(step) for step in steps),
        "steps": steps,
    }

    try:
        scene_memory_result = shared_scene_memory.record_compound_result(
            original_prompt or " ".join(item.get("prompt", "") for item in dispatch),
            dispatch,
            result,
        )
        result["scene_memory"] = scene_memory_result

        created = scene_memory_result.get("candidates_created") or []
        if created:
            result["respuesta"] += ". Detecte un nuevo patron de escena y lo deje como candidato."
    except Exception as e:
        print(f"   ⚠️ Error registrando memoria de escena compuesta: {e}")
        result["scene_memory"] = {"recorded": False, "error": str(e)}

    return result


def get_music_status_snapshot():
    snapshot = {
        "status": "ok",
        "active": None,
        "targets": {},
    }

    for plugin_name, target in (("music", "laptop"), ("music_local", "cellphone")):
        if plugin_name not in plugins:
            continue

        module = plugins[plugin_name]["module"]
        if not hasattr(module, "status"):
            continue

        try:
            data = module.status()
            if not isinstance(data, dict):
                data = {"status": "unknown"}
            data["plugin"] = plugin_name
            data.setdefault("target", target)
            snapshot["targets"][target] = data

            if data.get("running") or data.get("playing"):
                snapshot["active"] = data
        except Exception as e:
            snapshot["targets"][target] = {
                "status": "error",
                "plugin": plugin_name,
                "target": target,
                "error": str(e),
            }

    return snapshot


def extract_shared_scene_status_change(text: str):
    normalized = normalize_text(text)
    for word, action in (
        ("aprobar", "approved"),
        ("aprueba", "approved"),
        ("aproba", "approved"),
        ("rechazar", "rejected"),
        ("rechaza", "rejected"),
    ):
        if word in normalized:
            query = normalized.split(word, 1)[1].strip()
            query = query.replace("escena", "", 1).replace("patron", "", 1).strip()
            return action, query
    return None, None


def extract_shared_scene_activation(text: str):
    normalized = normalize_text(text)
    for phrase in ("activar escena", "activa escena", "ejecutar escena", "ejecuta escena"):
        if phrase in normalized:
            return normalized.split(phrase, 1)[1].strip()
    return None


def is_shared_scene_list_query(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        phrase in normalized
        for phrase in (
            "escenas aprendidas",
            "escenas guardadas",
            "listar escenas",
            "lista escenas",
            "muestra escenas",
            "ver escenas",
            "patrones",
            "automatizaciones",
        )
    )


def wants_music_local_fallback(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        phrase in normalized
        for phrase in (
            "musica local",
            "music local",
            "en celular",
            "al celular",
            "telefono",
            "android",
            "aca",
            "este dispositivo",
        )
    )


def wants_lights_only(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        phrase in normalized
        for phrase in (
            "solo luces",
            "solo luz",
            "sin musica",
            "aplica luces",
            "aplicar luces",
        )
    )


def music_node_available():
    if "music" not in plugins:
        return False, {"status": "missing_plugin", "target": "laptop"}

    module = plugins["music"]["module"]
    if not hasattr(module, "status"):
        return True, {"status": "unknown", "target": "laptop"}

    try:
        status = module.status()
    except Exception as exc:
        return False, {"status": "error", "target": "laptop", "error": str(exc)}

    if not isinstance(status, dict):
        return False, {"status": "invalid", "target": "laptop", "raw": str(status)}

    if status.get("status") in {"error", "offline", "unavailable"}:
        return False, status

    return True, status


def shared_scene_needs_music_confirmation(scene: dict, prompt: str):
    use_local = wants_music_local_fallback(prompt)
    lights_only = wants_lights_only(prompt)

    for action in scene.get("actions") or []:
        if not isinstance(action, dict) or action.get("domain") != "music":
            continue

        target = normalize_text(action.get("target") or "")
        plugin_name = action.get("plugin")
        wants_laptop = plugin_name == "music" or target in {"laptop", "pc", "nodo"}
        if not wants_laptop:
            continue

        available, status = music_node_available()
        if available:
            continue

        if lights_only:
            return None

        if use_local and "music_local" in plugins:
            return None

        return {
            "respuesta": (
                "La escena esta aprobada, pero no detecto el nodo de musica de la laptop. "
                "Dime 'activa escena "
                f"{scene.get('id')} con musica local' para usar el celular, o "
                f"'activa escena {scene.get('id')} solo luces' para aplicar solo las luces."
            ),
            "cerebro": "Core",
            "plugin": "domotica",
            "ok": False,
            "requires_confirmation": True,
            "needs_music_target_confirmation": True,
            "scene": scene,
            "music_status": status,
            "options": ["music_local", "lights_only"],
        }

    return None


def execute_shared_scene(scene: dict, prompt: str):
    confirmation = shared_scene_needs_music_confirmation(scene, prompt)
    if confirmation:
        return confirmation

    use_local = wants_music_local_fallback(prompt)
    lights_only = wants_lights_only(prompt)
    results = []

    for action in scene.get("actions") or []:
        if not isinstance(action, dict):
            continue

        domain = action.get("domain")
        if domain == "music":
            if lights_only:
                results.append({
                    "ok": True,
                    "plugin": "music",
                    "skipped": True,
                    "respuesta": "Musica omitida por confirmacion de solo luces.",
                })
                continue

            plugin_name = "music_local" if use_local else (action.get("plugin") or "music")
            if plugin_name == "music" and "music" not in plugins and "music_local" in plugins and use_local:
                plugin_name = "music_local"

            if plugin_name not in plugins:
                return {
                    "respuesta": f"No esta disponible el agente {plugin_name} para ejecutar la musica de la escena.",
                    "cerebro": "Core",
                    "plugin": "domotica",
                    "ok": False,
                    "requires_confirmation": True,
                    "scene": scene,
                }

            query = action.get("query") or action.get("genre") or "musica"
            results.append(execute_plugin(plugin_name, f"reproduce {query}"))
            continue

        if domain == "domotica":
            plugin_name = action.get("plugin") or "domotica"
            if plugin_name not in plugins:
                return {
                    "respuesta": f"No esta disponible el agente {plugin_name} para ejecutar las luces de la escena.",
                    "cerebro": "Core",
                    "plugin": "domotica",
                    "ok": False,
                    "scene": scene,
                }

            module = plugins[plugin_name]["module"]
            device = action.get("device")
            scene_data = action.get("scene") or {}
            if hasattr(module, "apply_scene_to_device"):
                light_result = module.apply_scene_to_device(device, scene_data)
            elif hasattr(module, "apply_scene"):
                light_result = module.apply_scene(scene_data)
            else:
                light_result = execute_plugin(plugin_name, f"luz escena {action.get('scene_name') or 'normal'}")

            if not isinstance(light_result, dict):
                light_result = {"respuesta": str(light_result)}
            light_result.setdefault("plugin", plugin_name)
            light_result.setdefault("ok", True)
            light_result.setdefault("respuesta", f"Luz {action.get('scene_name') or 'escena'} aplicada")
            results.append(light_result)
            continue

        results.append({
            "ok": False,
            "plugin": action.get("plugin"),
            "respuesta": f"Accion de escena no soportada: {domain}",
        })

    shared_scene_memory.mark_scene_executed(scene.get("id"))
    respuestas = [
        str(result.get("respuesta") or result.get("message") or result.get("plugin"))
        for result in results
        if isinstance(result, dict)
    ]
    return {
        "respuesta": f"Escena aplicada: {scene.get('name')}. " + " | ".join(respuestas),
        "cerebro": "Core",
        "plugin": "domotica",
        "compound": True,
        "ok": all(bool(result.get("ok", True)) for result in results if isinstance(result, dict)),
        "scene": scene,
        "steps": results,
    }


def handle_shared_scene_command(prompt: str):
    if is_shared_scene_list_query(prompt):
        scenes = shared_scene_memory.list_scenes()
        if not scenes:
            answer = "Todavia no hay escenas aprendidas."
        else:
            labels = [
                f"{scene.get('id')} ({scene.get('status')}): {scene.get('name')}"
                for scene in scenes[-5:]
            ]
            answer = "Escenas aprendidas: " + " | ".join(labels)
        return {
            "respuesta": answer,
            "cerebro": "Core",
            "plugin": "domotica",
            "scenes": scenes,
            "summary": shared_scene_memory.summary(),
        }

    status, query = extract_shared_scene_status_change(prompt)
    if status:
        scene = shared_scene_memory.find_scene(query)
        if not scene:
            return {
                "respuesta": "No encontre esa escena aprendida.",
                "cerebro": "Core",
                "plugin": "domotica",
                "ok": False,
            }
        updated = shared_scene_memory.update_scene_status(scene["id"], status)
        label = "aprobada" if status == "approved" else "rechazada"
        return {
            "respuesta": f"Escena {label}: {updated.get('name')}",
            "cerebro": "Core",
            "plugin": "domotica",
            "ok": True,
            "scene": updated,
        }

    query = extract_shared_scene_activation(prompt)
    if query is not None:
        scene = shared_scene_memory.find_scene(query)
        if not scene:
            return {
                "respuesta": "No encontre esa escena aprendida.",
                "cerebro": "Core",
                "plugin": "domotica",
                "ok": False,
            }
        if scene.get("status") != "approved":
            return {
                "respuesta": f"La escena '{scene.get('name')}' existe, pero necesita aprobacion antes de ejecutarse.",
                "cerebro": "Core",
                "plugin": "domotica",
                "ok": False,
                "requires_confirmation": True,
                "scene": scene,
            }
        return execute_shared_scene(scene, prompt)

    return None


# ========== RUTAS ==========
@app.route("/")
def index():
    """Página principal."""
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    data, error = json_object_or_error(request)
    if error is not None:
        return error
    pregunta = (data.get("pregunta") or "").strip()

    if not pregunta:
        return jsonify({"respuesta": "Mensaje vacío", "cerebro": "Core"})

    print(f"\n📨 Consulta: {pregunta}")
    print("REMOTE_ADDR:", request.remote_addr)
    print("HOST:", request.host)

    if is_system_status_request(normalize_text(pregunta)):
        return jsonify(build_core_status_response(pregunta))

    available_plugins = list(plugins.keys())
    compound_dispatch = build_compound_dispatch(pregunta, available_plugins)

    if compound_dispatch:
        print("   🧩 Comando compuesto:")
        for item in compound_dispatch:
            print(f"      - {item['plugin']}: {item['prompt']}")
        return jsonify(execute_compound_dispatch(compound_dispatch, original_prompt=pregunta))

    plugin_name = route_query(pregunta, available_plugins)

    if plugin_name == "domotica":
        shared_scene_response = handle_shared_scene_command(pregunta)
        if shared_scene_response is not None:
            update_context("domotica", pregunta)
            return jsonify(shared_scene_response)

    print(f"   🎯 Delegando a: {plugin_name}")

    if plugin_name in plugins:
        plugin_info = plugins[plugin_name]
        module = plugin_info["module"]

        try:
            return jsonify(execute_plugin(plugin_name, pregunta))

        except Exception as e:
            print(f"   ❌ Error en plugin {plugin_name}: {e}")
            return jsonify({
                "respuesta": f"Error ejecutando plugin {plugin_name}: {str(e)}",
                "cerebro": "Core",
                "plugin": plugin_name
            }), 500

    print("   ⚠️ Plugin devuelto por router no encontrado")
    return jsonify({
        "respuesta": "No sé cómo responder a eso. ¿Puedes reformular?",
        "cerebro": "Core",
        "sugerencia": "Consulta disponible en: " + ", ".join(list(plugins.keys()))
    })

@app.route("/ask_stream", methods=["POST"])
def ask_stream():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    data, error = json_object_or_error(request)
    if error is not None:
        return error
    pregunta = (data.get("pregunta") or "").strip()

    if not pregunta:
        return jsonify({"respuesta": "Mensaje vacío", "cerebro": "Core"}), 400

    print(f"\n📨 Consulta streaming: {pregunta}")
    print("REMOTE_ADDR:", request.remote_addr)
    print("HOST:", request.host)

    if is_system_status_request(normalize_text(pregunta)):
        return jsonify(build_core_status_response(pregunta))

    available_plugins = list(plugins.keys())
    compound_dispatch = build_compound_dispatch(pregunta, available_plugins)

    if compound_dispatch:
        print("   🧩 Comando compuesto streaming:")
        for item in compound_dispatch:
            print(f"      - {item['plugin']}: {item['prompt']}")
        return jsonify(execute_compound_dispatch(compound_dispatch, original_prompt=pregunta))

    plugin_name = route_query(pregunta, available_plugins)

    if plugin_name == "domotica":
        shared_scene_response = handle_shared_scene_command(pregunta)
        if shared_scene_response is not None:
            update_context("domotica", pregunta)
            return jsonify(shared_scene_response)

    print(f"   🎯 Delegando streaming a: {plugin_name}")

    if plugin_name in plugins:
        plugin_info = plugins[plugin_name]
        module = plugin_info["module"]

        try:
            if hasattr(module, "handle_stream"):
                update_context(plugin_name, pregunta)
                return Response(
                    stream_with_context(module.handle_stream(pregunta)),
                    mimetype="application/x-ndjson",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )

            response = module.handle(pregunta)
            if not isinstance(response, dict):
                response = {"respuesta": str(response), "cerebro": plugin_name}

            response["plugin"] = plugin_name
            response["version"] = plugin_info["version"]
            update_context(plugin_name, pregunta)
            return jsonify(response)

        except Exception as e:
            print(f"   ❌ Error streaming plugin {plugin_name}: {e}")
            return jsonify({
                "respuesta": f"Error ejecutando plugin {plugin_name}: {str(e)}",
                "cerebro": "Core",
                "plugin": plugin_name
            }), 500

    print("   ⚠️ Plugin devuelto por router no encontrado")
    return jsonify({
        "respuesta": "No sé cómo responder a eso. ¿Puedes reformular?",
        "cerebro": "Core",
        "sugerencia": "Consulta disponible en: " + ", ".join(list(plugins.keys()))
    }), 404

@app.route("/ask_auth", methods=["POST"])
@app.route("/api/v1/auth/pin", methods=["POST"])
def ask_auth():
    acceso = acceso_ip_local(request)
    if acceso is not None:
        return acceso

    lockout = auth_lockout_response(request)
    if lockout is not None:
        return lockout

    data, error = json_object_or_error(request)
    if error is not None:
        return error
    pin = (data.get("pin") or "").strip()
    device_id = (data.get("device_id") or auth_client_key(request)).strip()
    device_name = (data.get("device_name") or "PEARL Client").strip()

    try:
        if "auth" not in plugins:
            return jsonify({"success": False, "message": "Plugin auth no cargado"}), 500

        module = plugins["auth"]["module"]

        if not hasattr(module, "authenticate"):
            return jsonify({"success": False, "message": "Plugin auth inválido"}), 500

        result = module.authenticate(pin)

        if result:
            clear_auth_failures(request)
            token = issue_session_token(device_id=device_id, device_name=device_name)
            session = device_session_store.validate(token) or {}
            return jsonify({
                "success": True,
                "message": "Acceso concedido, señor.",
                "token": f"Bearer {token}",
                "expires_in": SESSION_TTL_SECONDS,
                "session": session,
            })

        record_auth_failure(request)
        return jsonify({"success": False, "message": "PIN incorrecto."}), 403

    except Exception as e:
        print(f"Error interno auth: {type(e).__name__}: {e}")
        return jsonify({"success": False, "message": f"Error interno auth: {type(e).__name__}: {e}"}), 500


@app.route("/auth/session", methods=["GET"])
@app.route("/api/v1/auth/session", methods=["GET"])
def auth_session():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    token = bearer_token(request)
    if hmac.compare_digest(token, SECRET_TOKEN):
        return jsonify({
            "valid": True,
            "session_type": "master",
            "product": product_identity(),
        })

    session = device_session_store.validate(token)
    if not session:
        return jsonify({"error": "invalid_or_expired_session"}), 403
    return jsonify({
        "valid": True,
        "session_type": "device",
        "session": session,
        "product": product_identity(),
    })


@app.route("/auth/logout", methods=["POST"])
@app.route("/api/v1/auth/logout", methods=["POST"])
def auth_logout():
    acceso = acceso_ip_local(request)
    if acceso is not None:
        return acceso

    token = bearer_token(request)
    if not token or hmac.compare_digest(token, SECRET_TOKEN):
        return jsonify({"success": False, "error": "device_session_required"}), 400
    if not device_session_store.revoke(token):
        return jsonify({"success": False, "error": "invalid_or_expired_session"}), 403
    return jsonify({"success": True})


@app.route("/plugins", methods=["GET"])
def list_plugins():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    return jsonify({
        "plugins": [
            {
                "name": name,
                "version": info["version"],
                "description": info["description"],
                "triggers": info["triggers"],
            }
            for name, info in plugins.items()
        ],
        "total": len(plugins),
    })


@app.route("/music/status", methods=["GET"])
def music_status():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    return jsonify(get_music_status_snapshot())


def get_domotica_module():
    if "domotica" not in plugins:
        raise RuntimeError("Plugin domotica no cargado")
    return plugins["domotica"]["module"]


@app.route("/devices", methods=["GET"])
def list_domotica_devices():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    module = get_domotica_module()
    if not hasattr(module, "list_devices"):
        return jsonify({"error": "domotica_devices_not_supported"}), 501
    return jsonify({"devices": module.list_devices()})


@app.route("/devices/candidates", methods=["GET"])
def list_domotica_device_candidates():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    module = get_domotica_module()
    if not hasattr(module, "list_pending_devices"):
        return jsonify({"error": "domotica_discovery_not_supported"}), 501
    return jsonify({"candidates": module.list_pending_devices()})


@app.route("/devices/discover", methods=["POST"])
def discover_domotica_devices():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    data, error = json_object_or_error(request)
    if error is not None:
        return error
    timeout = data.get("timeout")
    module = get_domotica_module()
    if not hasattr(module, "discover_devices"):
        return jsonify({"error": "domotica_discovery_not_supported"}), 501
    try:
        return jsonify(module.discover_devices(timeout=timeout))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/devices/candidates/<candidate_id>/approve", methods=["POST"])
def approve_domotica_device(candidate_id):
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    data, error = json_object_or_error(request)
    if error is not None:
        return error
    module = get_domotica_module()
    if not hasattr(module, "approve_device_candidate"):
        return jsonify({"error": "domotica_discovery_not_supported"}), 501
    try:
        result = module.approve_device_candidate(
            candidate_id,
            local_key=data.get("local_key") or "",
            name=data.get("name") or "",
            room=data.get("room") or "",
        )
        return jsonify(result)
    except ValueError as e:
        status = 400 if str(e) == "local_key_required" else 404
        return jsonify({"error": str(e)}), status


@app.route("/devices/candidates/<candidate_id>/reject", methods=["POST"])
def reject_domotica_device(candidate_id):
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    module = get_domotica_module()
    if not hasattr(module, "reject_device_candidate"):
        return jsonify({"error": "domotica_discovery_not_supported"}), 501
    try:
        return jsonify({"candidate": module.reject_device_candidate(candidate_id)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/scenes", methods=["GET"])
def list_shared_scenes():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    status = request.args.get("status")
    return jsonify({
        "scenes": shared_scene_memory.list_scenes(status=status),
        "summary": shared_scene_memory.summary(),
    })


@app.route("/scenes/candidates", methods=["GET"])
def list_shared_scene_candidates():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    return jsonify({
        "scenes": shared_scene_memory.list_scenes(status="candidate"),
    })


@app.route("/scenes/events", methods=["GET"])
def list_shared_scene_events():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50

    return jsonify({
        "events": shared_scene_memory.list_events(limit=max(1, min(limit, 200))),
    })


@app.route("/scenes/suggest", methods=["POST"])
def suggest_shared_scene():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    context, error = json_object_or_error(request)
    if error is not None:
        return error
    suggestion = shared_scene_memory.suggest_scene(context)
    if not suggestion:
        return jsonify({
            "suggestion": None,
            "requires_confirmation": True,
        })

    return jsonify(suggestion)


@app.route("/scenes/<scene_id>/approve", methods=["POST"])
def approve_shared_scene(scene_id):
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    scene = shared_scene_memory.update_scene_status(scene_id, "approved")
    if not scene:
        return jsonify({"error": "scene_not_found"}), 404
    return jsonify({"scene": scene})


@app.route("/scenes/<scene_id>/reject", methods=["POST"])
def reject_shared_scene(scene_id):
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    scene = shared_scene_memory.update_scene_status(scene_id, "rejected")
    if not scene:
        return jsonify({"error": "scene_not_found"}), 404
    return jsonify({"scene": scene})


@app.route("/health", methods=["GET"])
@app.route("/api/v1/health", methods=["GET"])
def health():
    """Estado del sistema."""
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    return jsonify({
        "status": "online",
        "product": product_identity(),
        "plugins": len(plugins),
        "versions": {name: info["version"] for name, info in plugins.items()},
        "plugin_errors": plugin_errors,
        "scene_memory": shared_scene_memory.summary(),
    })

@app.route("/ai/status", methods=["GET"])
def ai_status():
    """Estado de IA local/cloud para la UI."""
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    return jsonify(build_ai_status_response())

@app.route("/network", methods=["GET"])
def network():
    """Devuelve la IP LAN actual y URLs útiles para la UI."""
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    lan_ip = get_current_lan_ip()
    return jsonify({
        "localhost": f"http://127.0.0.1:{CORE_PORT}",
        "lan_ip": lan_ip,
        "lan_url": f"http://{lan_ip}:{CORE_PORT}",
        "port": CORE_PORT
    })


if __name__ == "__main__":
    guard_core_execution()
    load_plugins()
    print("\n🚀 JARVIS CORE iniciado")
    print(f"   🌐 http://localhost:{CORE_PORT}")
    print(f"   📦 Plugins activos: {len(plugins)}\n")
    app.run(host=CORE_HOST, port=CORE_PORT, debug=CORE_DEBUG)
