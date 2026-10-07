#!/usr/bin/env python3
"""
JARVIS CORE - Sistema de Plugins Modular
El core solo orquesta, nunca ejecuta comandos peligrosos.
"""

import json
import atexit
import importlib
import base64
import hashlib
import hmac
import ipaddress
import os
import re
import socket
import time
import uuid
from pathlib import Path
import requests
from action_proposals import (
    ActionProposalStore,
    ProposalAccessDenied,
    ProposalNotFound,
    ProposalStateError,
    canonical_hash,
)
from action_policy import (
    LEVEL_BLOCKED,
    LEVEL_CONFIRM,
    LEVEL_RESPOND_ONLY,
    LEVEL_SAFE,
    blocked_prompt_reason,
    classify_plan,
)
from device_sessions import DeviceSessionStore
from brain_notify import approval_decided, approval_waiting, pulse_route
from nova_event_bus import NovaEventBus
from router import (
    classify_query,
    is_system_status_request,
    normalize_text,
    route_query,
    update_context,
)
from flask import g, Flask, Response, render_template, request, jsonify, stream_with_context
from flask_cors import CORS

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:  # pragma: no cover - depends on deployment environment
    InvalidSignature = None
    hashes = None
    serialization = None
    padding = None

app = Flask(__name__)
CORS(app)

# ========== CONFIGURACIÓN ==========
BASE_DIR = Path(__file__).resolve().parent


# JARVIS_ENV_FILE elige otro archivo; vacío desactiva la carga (pruebas aisladas).
ENV_FILE = os.getenv("JARVIS_ENV_FILE", str(BASE_DIR / ".env"))
ENV_FILE_LOADED = None


def load_env_file(path: Path | None = None):
    """Carga .env simple sin agregar dependencia externa."""
    global ENV_FILE_LOADED
    if path is None:
        if not ENV_FILE:
            return
        path = Path(ENV_FILE).expanduser()
    if not path.exists():
        return
    ENV_FILE_LOADED = path

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

from branches.scene_memory import SharedSceneMemory


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


INSECURE_SECRET_TOKENS = frozenset({"jarvis_local_123"})
MIN_SECRET_TOKEN_LENGTH = 32


def configured_master_token(value: str) -> str:
    """Deshabilita el token maestro si falta, es corto o es un valor publicado."""
    value = (value or "").strip()
    if value in INSECURE_SECRET_TOKENS or len(value) < MIN_SECRET_TOKEN_LENGTH:
        return ""
    return value


SECRET_TOKEN = configured_master_token(os.getenv("JARVIS_SECRET_TOKEN", ""))
if not SECRET_TOKEN:
    print(
        "⚠️ JARVIS_SECRET_TOKEN ausente o inseguro: token maestro deshabilitado. "
        f"Usa un valor aleatorio de al menos {MIN_SECRET_TOKEN_LENGTH} caracteres."
    )
CORE_HOST = os.getenv("JARVIS_CORE_HOST", "0.0.0.0")
CORE_PORT = int(os.getenv("JARVIS_CORE_PORT", "5004"))
CORE_DEBUG = os.getenv("JARVIS_CORE_DEBUG", "false").lower() in {"1", "true", "yes"}
PEARL_PRODUCT = os.getenv("PEARL_PRODUCT", "PEARL Lite").strip() or "PEARL Lite"
PEARL_EDITION = os.getenv("PEARL_EDITION", "lite").strip().lower() or "lite"
PEARL_VERSION = os.getenv("PEARL_VERSION", "0.7.0-beta.1").strip() or "0.7.0-beta.1"
PEARL_API_VERSION = "v1"
SESSION_TTL_SECONDS = int(os.getenv("JARVIS_SESSION_TTL_SECONDS", "2592000"))
DEVICE_SESSION_MAX = int(os.getenv("PEARL_DEVICE_SESSION_MAX", "100"))
DEVICE_SESSIONS_FILE = Path(os.getenv("PEARL_DEVICE_SESSIONS_FILE", str(Path.home() / ".local/share/pearl-home/device_sessions.json")))
AUTH_MAX_ATTEMPTS = int(os.getenv("JARVIS_AUTH_MAX_ATTEMPTS", "5"))
AUTH_LOCKOUT_SECONDS = int(os.getenv("JARVIS_AUTH_LOCKOUT_SECONDS", "300"))
JINNEX_WATCH_SCOPES = tuple(
    scope.strip()
    for scope in os.getenv(
        "PEARL_JINNEX_WATCH_SCOPES",
        "nova.chat,codex.read,pearl.query,jinnex.memory.decide",
    ).split(",")
    if scope.strip()
)
JINNEX_WATCH_DEVICE_ALLOWLIST = frozenset(
    device_id.strip()
    for device_id in os.getenv("PEARL_JINNEX_WATCH_DEVICE_ALLOWLIST", "").split(",")
    if device_id.strip()
)
BRANCHES_DIR = Path(os.getenv("JARVIS_BRANCHES_DIR", str(BASE_DIR / "branches")))
MANIFEST_FILE = Path(os.getenv("JARVIS_MANIFEST_FILE", str(BASE_DIR / "plugin_manifest.json")))
AI_PROVIDER = os.getenv("JARVIS_AI_PROVIDER", "local").strip().lower() or "local"
OPENROUTER_API_URL = os.getenv(
    "OPENROUTER_API_URL",
    "https://openrouter.ai/api/v1",
).rstrip("/")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "deepseek/deepseek-v4-flash",
).strip()
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "PEARL HOME").strip()
# Se conservan estos alias internos para no romper el contrato de /ai/status.
LOCAL_AI_URL = OPENROUTER_API_URL
LOCAL_AI_MODEL = OPENROUTER_MODEL
CLOUD_AI_ENABLED = env_bool("JARVIS_CLOUD_AI_ENABLED", "true")
CLOUD_AI_PROVIDER = os.getenv("JARVIS_CLOUD_AI_PROVIDER", "").strip()
CLOUD_AI_HEALTH_URL = os.getenv("JARVIS_CLOUD_AI_HEALTH_URL", "").strip()
AI_STATUS_TIMEOUT = env_float("JARVIS_AI_STATUS_TIMEOUT", "2")
HUB_URL = os.getenv("JARVIS_ORCHESTRATOR_URL", "http://jarvis-node.local:5006").rstrip("/")
HUB_API_TIMEOUT = env_float("PEARL_HUB_API_TIMEOUT", "8")
HUB_GATEWAY_TOKEN = os.getenv("PEARL_CORE_GATEWAY_TOKEN", "").strip()
DEVICE_SIGNATURE_MAX_SKEW_SECONDS = int(os.getenv("PEARL_DEVICE_SIGNATURE_MAX_SKEW_SECONDS", "300"))
ACTION_PROPOSAL_TTL_SECONDS = int(os.getenv("PEARL_ACTION_PROPOSAL_TTL_SECONDS", "180"))
ACTION_PROPOSALS_FILE = Path(os.getenv(
    "PEARL_ACTION_PROPOSALS_FILE",
    str(Path.home() / ".local/share/pearl-home/action_proposals.json"),
))
NOVA_ENABLED = env_bool("PEARL_NOVA_ENABLED", "false")
NOVA_URL = os.getenv("PEARL_NOVA_URL", "http://127.0.0.1:5010").rstrip("/")
NOVA_EVENT_DB = Path(os.path.expanduser(os.getenv(
    "PEARL_NOVA_EVENT_DB",
    "~/.local/share/pearl-home/nova_event_bus.db",
)))
NOVA_EVENT_TIMEOUT = env_float("PEARL_NOVA_EVENT_TIMEOUT_SECONDS", "5")
NOVA_EVENT_RETRY = env_float("PEARL_NOVA_EVENT_RETRY_SECONDS", "15")
plugins = {}
plugin_errors = {}
shared_scene_memory = SharedSceneMemory()
device_session_store = DeviceSessionStore(DEVICE_SESSIONS_FILE, SESSION_TTL_SECONDS, DEVICE_SESSION_MAX)
action_proposal_store = ActionProposalStore(ACTION_PROPOSALS_FILE, ACTION_PROPOSAL_TTL_SECONDS)
auth_failures = {}
device_signature_nonces = {}
_nova_event_bus = None

ACTION_ACCEPT_PHRASES = {
    "si",
    "confirmo",
    "confirmar",
    "confirma",
    "si confirmo",
    "si confirmar",
    "si confirma",
    "si hazlo",
    "si por favor",
    "confirmado",
    "confirmada",
    "si confirmado",
}
ACTION_CANCEL_PHRASES = {
    "no",
    "cancelar",
    "cancela",
    "cancelalo",
    "rechazar",
    "rechaza",
    "rechazo",
    "no lo hagas",
    "cancelado",
    "cancelada",
    "rechazado",
    "mejor no",
    "no gracias",
    "dejalo",
    "olvidalo",
}

COMPOUND_CONNECTOR_RE = re.compile(
    r"\s+(?:y|e|tambien|también|ademas|además|luego|despues|después)\s+"
    r"(?=(?:prende|enciende|apaga|apagar|encender|reproduce|reproducir|pon|play|"
    r"pausa|reanuda|continua|activa|activar|restaurar|deshacer|estado|luz|"
    r"lampara|lámpara|domotica|domótica|musica|música)\b)",
    re.IGNORECASE,
)


def get_nova_event_bus():
    global _nova_event_bus
    configured = app.config.get("NOVA_EVENT_BUS")
    if configured is not None:
        return configured
    if not NOVA_ENABLED:
        return None
    if _nova_event_bus is None:
        _nova_event_bus = NovaEventBus(
            NOVA_EVENT_DB,
            NOVA_URL,
            timeout_seconds=NOVA_EVENT_TIMEOUT,
            retry_seconds=NOVA_EVENT_RETRY,
        )
    return _nova_event_bus


def publish_compound_result_to_nova(prompt: str, payload: dict) -> str | None:
    """Persistir una observación compuesta sin dar autoridad a Nova."""
    try:
        event_bus = get_nova_event_bus()
        if event_bus is None:
            return None
        return event_bus.publish_compound_response(prompt, payload)
    except Exception:
        # Nova es observador: nunca puede afectar el resultado de PEARL.
        return None


@app.after_request
def publish_compound_event_to_nova(response):
    """Observar respuestas compuestas sin alterar su resultado ni ejecución."""
    if request.method != "POST" or request.path not in {"/ask", "/ask_stream"}:
        return response
    payload = response.get_json(silent=True)
    if not isinstance(payload, dict) or not payload.get("compound"):
        return response
    request_payload = request.get_json(silent=True) or {}
    publish_compound_result_to_nova(
        request_payload.get("pregunta", ""),
        payload,
    )
    return response


def product_identity():
    return {
        "name": PEARL_PRODUCT,
        "edition": PEARL_EDITION,
        "version": PEARL_VERSION,
        "api_version": PEARL_API_VERSION,
    }


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
    if is_master_token(token):
        return True
    return session_token_valido(token)


def is_master_token(token: str) -> bool:
    return bool(SECRET_TOKEN and token) and hmac.compare_digest(token, SECRET_TOKEN)


def bearer_token(req) -> str:
    auth = req.headers.get("Authorization", "").strip()
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return ""
    return auth[len(prefix):].strip()


def cleanup_expired_sessions():
    return device_session_store.prune()


def issue_session_token(
    device_id: str = "",
    device_name: str = "",
    device_public_key: str = "",
    *,
    audience: str = "pearl-client",
    scopes=("pearl.ask", "jinnex.query", "jinnex.memory.decide"),
) -> str:
    return device_session_store.issue(
        device_id=device_id,
        device_name=device_name,
        device_public_key=device_public_key,
        audience=audience,
        scopes=scopes,
    )


def session_token_valido(token: str) -> bool:
    return device_session_store.validate(token) is not None


def current_device_session(req):
    token = bearer_token(req)
    if not token or is_master_token(token):
        return None
    return device_session_store.validate(token)


def is_loopback_request(req) -> bool:
    try:
        return ipaddress.ip_address(req.remote_addr or "").is_loopback
    except ValueError:
        return False


def tunnel_client_ip(req) -> str:
    """IP pública fijada por Cloudflare; vacía si la petición no viene del túnel."""
    if not is_loopback_request(req):
        return ""
    forwarded = req.headers.get("CF-Connecting-IP", "").strip()
    if not forwarded:
        return ""
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return "invalid"


def auth_client_key(req) -> str:
    # Detrás del túnel todo llega desde loopback: se identifica por la IP real.
    tunnel_ip = tunnel_client_ip(req)
    if tunnel_ip:
        return f"tunnel:{tunnel_ip}"
    forwarded = req.headers.get("X-Jinnex-Client-Key", "").strip().lower()
    if is_loopback_request(req) and re.fullmatch(r"[0-9a-f]{64}", forwarded):
        return f"jinnex:{forwarded}"
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

@app.before_request
def bind_jinnex_device_identity():
    # Sólo Core autenticado deriva esta credencial; nunca viene del texto/modelo.
    session = current_device_session(request)
    g.jinnex_device_authorization = (
        request.headers.get("Authorization", "") if session else ""
    )


def handle_jinnex_memory_command(text):
    match = re.fullmatch(r"/(confirmar_memoria|rechazar_memoria|memorias_pendientes)(?:\s+(\S+))?", text.strip())
    if match is None:
        return None
    authorization = getattr(g, "jinnex_device_authorization", "")
    if not authorization:
        return jsonify({"respuesta": "Vincula una sesión de dispositivo para decidir memorias.",
                        "status": "denied", "plugin": "jinnex"}), 403
    command, operation_id = match.groups()
    if command == "memorias_pendientes":
        if operation_id:
            return jsonify({"respuesta": "El listado de pendientes no lleva identificador."}), 400
        body = {"pending": True}
    else:
        if not operation_id:
            return jsonify({"respuesta": "Indica el identificador de la propuesta de memoria."}), 400
        body = {"confirmation": {"operation_id": operation_id,
                                 "decision": "approve" if command == "confirmar_memoria" else "reject"}}
    try:
        response = requests.post(f"{NOVA_URL}/v1/query", json=body,
                                 headers={"Authorization": authorization}, timeout=(2, 15))
        result = response.json()
        if response.status_code != 200:
            return jsonify({"respuesta": "No se pudo decidir la propuesta. Puede haber expirado o pertenecer a otra sesión.",
                            "plugin": "jinnex", "status": "failed"}), response.status_code
        if command == "memorias_pendientes":
            pending = result.get("pending", [])
            lines = [f"{item['summary']}\n/confirmar_memoria {item['operation_id']} o /rechazar_memoria {item['operation_id']}"
                     for item in pending]
            answer = "\n\n".join(lines) if lines else "No hay propuestas de memoria pendientes."
        else:
            pending = []
            answer = result["output"]["text"]
        return jsonify({"respuesta": answer, "plugin": "jinnex", "cerebro": "jinnex",
                        "status": result['status'], "memory_pending": pending})
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        return jsonify({"respuesta": "Jinnex no está disponible para decidir la memoria. Intenta de nuevo con la misma propuesta.",
                        "plugin": "jinnex", "status": "failed"}), 503


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


def request_signing_path(req) -> str:
    query = req.query_string.decode("utf-8", errors="ignore")
    return f"{req.path}?{query}" if query else req.path


def request_body_hash(req) -> str:
    return hashlib.sha256(req.get_data(cache=True) or b"").hexdigest()


def device_signing_payload(req, timestamp: str, nonce: str) -> str:
    return "\n".join([
        req.method.upper(),
        request_signing_path(req),
        timestamp,
        nonce,
        request_body_hash(req),
    ])


def prune_device_signature_nonces(now: float):
    cutoff = now - DEVICE_SIGNATURE_MAX_SKEW_SECONDS
    expired = [key for key, seen_at in device_signature_nonces.items() if seen_at < cutoff]
    for key in expired:
        device_signature_nonces.pop(key, None)


def validate_device_signature(req, session: dict):
    if serialization is None or padding is None or hashes is None:
        return jsonify({"error": "device_signature_unavailable"}), 503

    device_id = (req.headers.get("X-PEARL-Device-Id") or "").strip()
    timestamp = (req.headers.get("X-PEARL-Timestamp") or "").strip()
    nonce = (req.headers.get("X-PEARL-Nonce") or "").strip()
    signature_value = (req.headers.get("X-PEARL-Signature") or "").strip()
    public_key_value = (session.get("device_public_key") or "").strip()

    if not all((device_id, timestamp, nonce, signature_value, public_key_value)):
        return jsonify({"error": "device_signature_required"}), 403
    if device_id != (session.get("device_id") or ""):
        return jsonify({"error": "device_session_mismatch"}), 403

    try:
        signed_at = int(timestamp)
    except ValueError:
        return jsonify({"error": "invalid_device_timestamp"}), 403

    now = time.time()
    if abs(now - signed_at) > DEVICE_SIGNATURE_MAX_SKEW_SECONDS:
        return jsonify({"error": "device_signature_expired"}), 403

    prune_device_signature_nonces(now)
    nonce_key = f"{device_id}:{nonce}"
    if nonce_key in device_signature_nonces:
        return jsonify({"error": "device_signature_replay"}), 403

    try:
        public_key = serialization.load_der_public_key(base64.b64decode(public_key_value))
        signature = base64.b64decode(signature_value)
        public_key.verify(
            signature,
            device_signing_payload(req, timestamp, nonce).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (ValueError, TypeError, InvalidSignature):
        return jsonify({"error": "invalid_device_signature"}), 403

    device_signature_nonces[nonce_key] = now
    return None


def scene_prompt_gateway_access(req):
    acceso = acceso_local_autorizado(req)
    if acceso is not None:
        return None, acceso

    token = bearer_token(req)
    if is_master_token(token):
        return {"session_type": "master"}, None

    session = current_device_session(req)
    if not session:
        return None, (jsonify({"error": "invalid_or_expired_session"}), 403)

    signature_error = validate_device_signature(req, session)
    if signature_error is not None:
        return None, signature_error

    return {"session_type": "device", "session": session}, None


def hub_gateway_headers(session_context=None):
    headers = {}
    if HUB_GATEWAY_TOKEN:
        headers["X-PEARL-Core-Gateway"] = HUB_GATEWAY_TOKEN
    session = (session_context or {}).get("session") or {}
    if session:
        headers["X-PEARL-Device-Id"] = session.get("device_id", "")
        headers["X-PEARL-Device-Name"] = session.get("device_name", "")
    return {key: value for key, value in headers.items() if value}


def hub_api_response(method: str, path: str, json_data=None, params=None, session_context=None):
    request_kwargs = {
        "json": json_data,
        "params": params,
        "timeout": (3, HUB_API_TIMEOUT),
    }
    headers = hub_gateway_headers(session_context)
    if headers:
        request_kwargs["headers"] = headers

    try:
        response = requests.request(
            method,
            f"{HUB_URL}{path}",
            **request_kwargs,
        )
    except requests.RequestException as exc:
        return jsonify({
            "status": "error",
            "error": "hub_unavailable",
            "detail": str(exc),
        }), 503

    try:
        payload = response.json()
    except ValueError:
        payload = {"status": "error", "error": "invalid_hub_response"}
    return jsonify(payload), response.status_code


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


def action_requester(req) -> dict:
    token = bearer_token(req)
    if is_master_token(token):
        return {"type": "master", "id": "master", "name": "PEARL master token"}

    session = current_device_session(req) or {}
    return {
        "type": "device",
        "id": session.get("device_id") or auth_client_key(req),
        "name": session.get("device_name") or "PEARL Client",
    }


def build_plugin_plan(plugin_name: str, prompt: str):
    if plugin_name not in plugins:
        return None
    module = plugins[plugin_name]["module"]
    if not hasattr(module, "build_plan") or not hasattr(module, "execute_confirmed_plan"):
        return None
    plan = module.build_plan(prompt)
    if not isinstance(plan, dict):
        raise ValueError("plugin_plan_must_be_object")
    return plan


def summarize_plugin_plan(plugin_name: str, plan: dict) -> str:
    labels = []
    for action in plan.get("actions") or []:
        if not isinstance(action, dict):
            continue
        action_type = action.get("type") or "accion"
        device = action.get("device")
        scene_name = action.get("scene_name")
        query = action.get("query")
        detail = scene_name or query or device
        labels.append(f"{action_type}: {detail}" if detail else str(action_type))
    detail = ", ".join(labels) or (plan.get("intent") or "accion")
    return f"{plugin_name}: {detail}"


def create_proposal_response(kind: str, envelope: dict, summary: str, req):
    proposal = action_proposal_store.create(
        kind=kind,
        plan=envelope,
        summary=summary,
        requester=action_requester(req),
    )
    public = action_proposal_store.public(proposal)
    approval_waiting(proposal["id"], summary, action_proposal_store.ttl_seconds)
    return {
        "respuesta": f"Necesito tu confirmacion para ejecutar: {summary}.",
        "cerebro": "Core",
        "plugin": envelope.get("plugin") or kind,
        "status": "confirmation_required",
        "action_level": LEVEL_CONFIRM,
        "requires_confirmation": True,
        "proposal": public,
    }


def blocked_action_response(reason: str, plugin_name: str = "core"):
    return {
        "respuesta": "Esta accion esta bloqueada por la politica de seguridad de PEARL.",
        "cerebro": "Core",
        "plugin": plugin_name,
        "status": "blocked",
        "action_level": LEVEL_BLOCKED,
        "reason": reason,
        "requires_confirmation": False,
    }


def maybe_handle_plugin_plan(plugin_name: str, prompt: str, req):
    plan = build_plugin_plan(plugin_name, prompt)
    if not plan:
        return None
    level = classify_plan(plugin_name, plan)
    if level == LEVEL_RESPOND_ONLY:
        return None
    envelope = {
        "kind": "plugin_plan",
        "plugin": plugin_name,
        "prompt": prompt,
        "plan": plan,
    }
    if level == LEVEL_BLOCKED:
        return blocked_action_response("accion_no_permitida", plugin_name)
    if level == LEVEL_CONFIRM:
        plan["requires_confirmation"] = True
        return create_proposal_response(
            "plugin_plan",
            envelope,
            summarize_plugin_plan(plugin_name, plan),
            req,
        )

    plan["requires_confirmation"] = False
    response = execute_confirmed_plugin_plan(envelope)
    response["action_level"] = LEVEL_SAFE
    response["requires_confirmation"] = False
    return response


def maybe_propose_compound_action(dispatch: list, original_prompt: str, req):
    planned_steps = []
    highest_level = LEVEL_RESPOND_ONLY
    for item in dispatch:
        plan = build_plugin_plan(item["plugin"], item["prompt"])
        if plan is None:
            return None
        level = classify_plan(item["plugin"], plan)
        highest_level = max(highest_level, level)
        plan["requires_confirmation"] = level == LEVEL_CONFIRM
        planned_steps.append({
            "plugin": item["plugin"],
            "domain": item.get("domain"),
            "prompt": item["prompt"],
            "plan": plan,
        })

    if highest_level == LEVEL_RESPOND_ONLY:
        return None
    summary = " | ".join(
        summarize_plugin_plan(item["plugin"], item["plan"])
        for item in planned_steps
    )
    envelope = {
        "kind": "compound_plan",
        "plugin": "compound",
        "prompt": original_prompt,
        "steps": planned_steps,
    }
    if highest_level == LEVEL_BLOCKED:
        return blocked_action_response("plan_compuesto_no_permitido", "compound")
    if highest_level == LEVEL_CONFIRM:
        return create_proposal_response("compound_plan", envelope, summary, req)

    response = execute_confirmed_compound(envelope)
    response["action_level"] = LEVEL_SAFE
    response["requires_confirmation"] = False
    return response


def maybe_propose_shared_scene(prompt: str, req):
    query = extract_shared_scene_activation(prompt)
    if query is None:
        return None
    scene = shared_scene_memory.find_scene(query)
    if not scene or scene.get("status") != "approved":
        return None
    preflight = shared_scene_needs_music_confirmation(scene, prompt)
    if preflight:
        return preflight
    envelope = {
        "kind": "shared_scene",
        "plugin": "domotica",
        "prompt": prompt,
        "scene_id": scene.get("id"),
        "scene_actions_hash": canonical_hash(scene.get("actions") or []),
    }
    return create_proposal_response(
        "shared_scene",
        envelope,
        f"activar escena {scene.get('name') or scene.get('id')}",
        req,
    )


def execute_confirmed_plugin_plan(envelope: dict):
    plugin_name = envelope.get("plugin")
    if plugin_name not in plugins:
        raise ValueError("proposal_plugin_unavailable")
    module = plugins[plugin_name]["module"]
    if not hasattr(module, "execute_confirmed_plan"):
        raise ValueError("proposal_execution_not_supported")
    response = module.execute_confirmed_plan(envelope.get("plan") or {}, envelope.get("prompt") or "")
    if not isinstance(response, dict):
        response = {"respuesta": str(response), "cerebro": plugin_name}
    response["plugin"] = plugin_name
    response["version"] = plugins[plugin_name]["version"]
    update_context(plugin_name, envelope.get("prompt") or "")
    return response


def compound_result(steps: list, dispatch: list, original_prompt: str):
    def step_ok(step):
        if step.get("error"):
            return False
        if "ok" in step and not bool(step.get("ok")):
            return False
        nested_status = step.get("status")
        return not (isinstance(nested_status, dict) and nested_status.get("status") == "error")

    result = {
        "respuesta": " | ".join(
            str(step.get("respuesta") or step.get("message") or step.get("plugin"))
            for step in steps
        ),
        "cerebro": "Core",
        "plugin": "compound",
        "compound": True,
        "ok": all(step_ok(step) for step in steps),
        "steps": steps,
    }
    try:
        memory_result = shared_scene_memory.record_compound_result(
            original_prompt,
            dispatch,
            result,
        )
        result["scene_memory"] = memory_result
        if memory_result.get("candidates_created"):
            result["respuesta"] += ". Detecte un nuevo patron de escena y lo deje como candidato."
    except Exception as exc:
        result["scene_memory"] = {"recorded": False, "error": str(exc)}
    return result


def execute_confirmed_compound(envelope: dict):
    steps = []
    dispatch = []
    for item in envelope.get("steps") or []:
        response = execute_confirmed_plugin_plan(item)
        response["compound_prompt"] = item.get("prompt")
        steps.append(response)
        dispatch.append({
            "plugin": item.get("plugin"),
            "domain": item.get("domain"),
            "prompt": item.get("prompt"),
        })
    return compound_result(steps, dispatch, envelope.get("prompt") or "")


def execute_confirmed_proposal(proposal: dict):
    envelope = proposal.get("plan") or {}
    kind = proposal.get("kind") or envelope.get("kind")
    if kind == "plugin_plan":
        return execute_confirmed_plugin_plan(envelope)
    if kind == "compound_plan":
        return execute_confirmed_compound(envelope)
    if kind == "shared_scene":
        scene = shared_scene_memory.find_scene(envelope.get("scene_id") or "")
        if not scene or scene.get("status") != "approved":
            raise ValueError("proposal_scene_unavailable")
        if canonical_hash(scene.get("actions") or []) != envelope.get("scene_actions_hash"):
            raise ValueError("proposal_scene_changed")
        return execute_shared_scene(scene, envelope.get("prompt") or "")
    raise ValueError("proposal_kind_not_supported")


def action_result_succeeded(result: dict) -> bool:
    if result.get("error") or result.get("ok") is False:
        return False
    status = result.get("status")
    return not (isinstance(status, dict) and status.get("status") == "error")


def apply_action_decision(proposal_id: str, decision: str, idempotency_key: str, requester: dict):
    try:
        proposal, changed = action_proposal_store.claim(
            proposal_id=proposal_id,
            decision=decision,
            idempotency_key=idempotency_key,
            requester=requester,
        )
    except ProposalNotFound as exc:
        return {"status": "error", "error": str(exc)}, 404
    except ProposalAccessDenied as exc:
        return {"status": "error", "error": str(exc)}, 403
    except ProposalStateError as exc:
        return {"status": "error", "error": str(exc)}, 409
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}, 400

    if not changed:
        public = action_proposal_store.public(proposal)
        return {
            "status": public.get("status"),
            "idempotent": True,
            "proposal": public,
            "result": public.get("result"),
        }, 200

    if proposal.get("decision") == "cancel":
        approval_decided(proposal_id, False, "cancelada")
        public = action_proposal_store.public(proposal)
        return {
            "status": "cancelled",
            "respuesta": "Accion cancelada. No se ejecuto ningun cambio.",
            "proposal": public,
        }, 200

    try:
        result = execute_confirmed_proposal(proposal)
        if not isinstance(result, dict):
            result = {"respuesta": str(result)}
        success = action_result_succeeded(result)
    except Exception as exc:
        result = {
            "respuesta": f"No pude ejecutar la accion confirmada: {exc}",
            "error": str(exc),
            "ok": False,
        }
        success = False

    completed = action_proposal_store.complete(proposal_id, result, success)
    approval_decided(proposal_id, success, "" if success else "falló")
    if success and result.get("compound"):
        envelope = proposal.get("plan") or {}
        publish_compound_result_to_nova(envelope.get("prompt") or "", result)
    public = action_proposal_store.public(completed)
    return {
        "status": public.get("status"),
        "respuesta": result.get("respuesta") or result.get("message"),
        "proposal": public,
        "result": result,
    }, 200 if success else 422


def natural_action_decision(prompt: str):
    normalized = normalize_text(prompt)
    if normalized in ACTION_ACCEPT_PHRASES:
        return "accept"
    if normalized in ACTION_CANCEL_PHRASES:
        return "cancel"
    return None


def pending_natural_decision(prompt: str, req) -> bool:
    """¿Es una decisión ("confirmado", "cancela") con una propuesta esperándola?"""
    if natural_action_decision(prompt) is None:
        return False
    return bool(action_proposal_store.list_pending(action_requester(req),
                                                   include_all_for_master=False))


def maybe_handle_natural_action_decision(prompt: str, req):
    decision = natural_action_decision(prompt)
    if decision is None:
        return None

    requester = action_requester(req)
    pending = action_proposal_store.list_pending(requester, include_all_for_master=False)
    if not pending:
        return None

    proposal = pending[-1]
    payload, status_code = apply_action_decision(
        proposal_id=proposal["id"],
        decision=decision,
        idempotency_key="natural-" + uuid.uuid4().hex,
        requester=requester,
    )
    payload["natural_confirmation"] = True
    return payload, status_code


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


def openrouter_model_names(payload):
    names = []
    models = payload.get("data", payload.get("models", []))
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("id") or item.get("name") or item.get("model")
        if name:
            names.append(str(name))
    return names


def model_name_matches(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return candidate == expected or candidate.split(":", 1)[0] == expected.split(":", 1)[0]


def openrouter_headers():
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME
    return headers


def check_local_ai_status():
    enabled = "local_ia" in plugins
    if NOVA_ENABLED:
        status = {
            "enabled": enabled,
            "provider": "jinnex-next",
            "url": NOVA_URL,
            "model": "nova-2.0.1",
            "configured": True,
            "connected": False,
            "model_available": False,
            "model_loaded": False,
            "status": "disabled" if not enabled else "disconnected",
            "error": None,
            "fallback_provider": "openrouter",
            "fallback_configured": bool(OPENROUTER_API_KEY),
        }
        if not enabled:
            status["error"] = "plugin local_ia no cargado"
            return status
        try:
            response = requests.get(
                f"{NOVA_URL}/health",
                timeout=AI_STATUS_TIMEOUT,
            )
            if response.status_code != 200:
                status["error"] = f"nova_http_{response.status_code}"
                return status
            payload = response.json()
            readiness = payload.get("readiness", {}) if isinstance(payload, dict) else {}
            connected = (isinstance(payload, dict) and payload.get("liveness") is True
                         and readiness.get("ready") is True)
            status["connected"] = connected
            status["model_available"] = connected
            # OpenRouter no permite afirmar que el modelo esté cargado localmente.
            status["model_loaded"] = False
            status["readiness"] = readiness
            status["dependencies"] = payload.get("dependencies", {}) if isinstance(payload, dict) else {}
            status["checked_at"] = payload.get("checked_at") if isinstance(payload, dict) else None
            status["degraded"] = isinstance(payload, dict) and payload.get("status") == "degraded"
            status["status"] = "degraded" if connected and status["degraded"] else "connected" if connected else "error"
            if not connected:
                status["error"] = "nova_not_ready"
            return status
        except Exception:
            status["error"] = "nova_health_unavailable"
            return status

    status = {
        "enabled": enabled,
        "provider": "openrouter",
        "url": LOCAL_AI_URL,
        "model": LOCAL_AI_MODEL,
        "configured": bool(OPENROUTER_API_KEY),
        "connected": False,
        "model_available": False,
        "model_loaded": False,
        "status": "disabled" if not enabled else "disconnected",
        "error": None,
    }

    if not enabled:
        status["error"] = "plugin local_ia no cargado"
        return status

    if not OPENROUTER_API_KEY:
        status["status"] = "not_configured"
        status["error"] = "OPENROUTER_API_KEY no configurada"
        return status

    try:
        models = requests.get(
            f"{LOCAL_AI_URL}/models",
            headers=openrouter_headers(),
            timeout=AI_STATUS_TIMEOUT,
        )
        if models.status_code != 200:
            status["error"] = f"openrouter_http_{models.status_code}"
            return status

        status["connected"] = True
        available_models = openrouter_model_names(models.json())
        status["model_available"] = any(
            model_name_matches(name, LOCAL_AI_MODEL)
            for name in available_models
        )
        status["status"] = "available" if status["model_available"] else "missing_model"

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


def is_nova_candidate_list_query(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        phrase in normalized
        for phrase in (
            "escenas candidatas",
            "candidatas de nova",
            "candidatas en nova",
            "candidatos de nova",
            "candidatos en nova",
            "eventos candidatos de nova",
        )
    )


def fetch_nova_complex_event_candidates(limit: int = 50) -> list[dict]:
    if not NOVA_ENABLED:
        raise RuntimeError("nova_disabled")
    bounded_limit = max(1, min(int(limit), 500))
    response = requests.get(
        f"{NOVA_URL}/v1/complex-events/candidates",
        params={"limit": bounded_limit},
        timeout=(1.0, NOVA_EVENT_TIMEOUT),
    )
    if response.status_code != 200:
        raise RuntimeError(f"nova_http_{response.status_code}")
    payload = response.json()
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(candidates, list) or not all(
        isinstance(candidate, dict) for candidate in candidates
    ):
        raise RuntimeError("nova_candidates_invalid_response")
    return candidates


def handle_nova_candidate_query(prompt: str):
    if not is_nova_candidate_list_query(prompt):
        return None
    try:
        candidates = fetch_nova_complex_event_candidates()
    except Exception:
        return {
            "respuesta": "No pude consultar ahora los candidatos de eventos compuestos en Nova.",
            "cerebro": "Core",
            "plugin": "nova",
            "ok": False,
            "status": "unavailable",
            "candidate_source": "nova_complex_events",
            "nova_candidates": [],
        }

    if not candidates:
        answer = "Nova no tiene candidatos de eventos compuestos."
    else:
        labels = []
        for candidate in candidates[:5]:
            summary = candidate.get("summary") or candidate.get("kind") or "evento compuesto"
            occurred_at = candidate.get("occurred_at")
            label = str(summary)
            if occurred_at:
                label += f" [{occurred_at}]"
            labels.append(label)
        answer = "Candidatos de eventos compuestos en Nova: " + " | ".join(labels)
    return {
        "respuesta": answer,
        "cerebro": "Core",
        "plugin": "nova",
        "ok": True,
        "candidate_source": "nova_complex_events",
        "nova_candidates": candidates,
        "count": len(candidates),
    }


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

    blocked_reason = blocked_prompt_reason(pregunta)
    if blocked_reason:
        return jsonify(blocked_action_response(blocked_reason))

    print(f"\n📨 Consulta: {pregunta}")
    print("REMOTE_ADDR:", request.remote_addr)
    print("HOST:", request.host)

    memory_decision = handle_jinnex_memory_command(pregunta)
    if memory_decision is not None:
        return memory_decision

    natural_decision = maybe_handle_natural_action_decision(pregunta, request)
    if natural_decision is not None:
        payload, status_code = natural_decision
        return jsonify(payload), status_code

    if is_system_status_request(normalize_text(pregunta)):
        return jsonify(build_core_status_response(pregunta))

    nova_candidate_response = handle_nova_candidate_query(pregunta)
    if nova_candidate_response is not None:
        update_context("nova", pregunta)
        return jsonify(nova_candidate_response)

    available_plugins = list(plugins.keys())
    compound_dispatch = build_compound_dispatch(pregunta, available_plugins)

    if compound_dispatch:
        pulse_route(*(item["plugin"] for item in compound_dispatch))
        print("   🧩 Comando compuesto:")
        for item in compound_dispatch:
            print(f"      - {item['plugin']}: {item['prompt']}")
        proposal = maybe_propose_compound_action(compound_dispatch, pregunta, request)
        if proposal is not None:
            return jsonify(proposal)
        return jsonify(execute_compound_dispatch(compound_dispatch, original_prompt=pregunta))

    plugin_name = route_query(pregunta, available_plugins)
    pulse_route(plugin_name)

    if plugin_name == "domotica":
        proposal = maybe_propose_shared_scene(pregunta, request)
        if proposal is not None:
            update_context("domotica", pregunta)
            return jsonify(proposal)
        shared_scene_response = handle_shared_scene_command(pregunta)
        if shared_scene_response is not None:
            update_context("domotica", pregunta)
            return jsonify(shared_scene_response)

    print(f"   🎯 Delegando a: {plugin_name}")

    if plugin_name in plugins:
        plugin_info = plugins[plugin_name]
        module = plugin_info["module"]

        try:
            planned_response = maybe_handle_plugin_plan(plugin_name, pregunta, request)
            if planned_response is not None:
                update_context(plugin_name, pregunta)
                return jsonify(planned_response)
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

@app.route("/api/v1/route", methods=["POST"])
def api_route():
    """Clasifica una consulta sin ejecutarla ni tocar el contexto.

    Nova (Jinnex) la usa para decidir si el texto es una orden para PEARL o
    una conversación: así el vocabulario de la casa vive sólo en router.py.
    """
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso
    data, error = json_object_or_error(request)
    if error is not None:
        return error
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"status": "error", "error": "text_required"}), 400
    if pending_natural_decision(text, request):
        # "Confirmado" sólo es una orden si este dispositivo tiene una propuesta
        # pendiente: así Nova la envía a /ask, que la aplica.
        classification = {"plugin": "core", "kind": "action"}
    else:
        classification = classify_query(text, list(plugins.keys()))
    pulse_route(classification["plugin"])
    return jsonify({"status": "ok", **classification})


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

    blocked_reason = blocked_prompt_reason(pregunta)
    if blocked_reason:
        return jsonify(blocked_action_response(blocked_reason))

    print(f"\n📨 Consulta streaming: {pregunta}")
    print("REMOTE_ADDR:", request.remote_addr)
    print("HOST:", request.host)

    memory_decision = handle_jinnex_memory_command(pregunta)
    if memory_decision is not None:
        return memory_decision

    natural_decision = maybe_handle_natural_action_decision(pregunta, request)
    if natural_decision is not None:
        payload, status_code = natural_decision
        return jsonify(payload), status_code

    if is_system_status_request(normalize_text(pregunta)):
        return jsonify(build_core_status_response(pregunta))

    nova_candidate_response = handle_nova_candidate_query(pregunta)
    if nova_candidate_response is not None:
        update_context("nova", pregunta)
        return jsonify(nova_candidate_response)

    available_plugins = list(plugins.keys())
    compound_dispatch = build_compound_dispatch(pregunta, available_plugins)

    if compound_dispatch:
        pulse_route(*(item["plugin"] for item in compound_dispatch))
        print("   🧩 Comando compuesto streaming:")
        for item in compound_dispatch:
            print(f"      - {item['plugin']}: {item['prompt']}")
        proposal = maybe_propose_compound_action(compound_dispatch, pregunta, request)
        if proposal is not None:
            return jsonify(proposal)
        return jsonify(execute_compound_dispatch(compound_dispatch, original_prompt=pregunta))

    plugin_name = route_query(pregunta, available_plugins)
    pulse_route(plugin_name)

    if plugin_name == "domotica":
        proposal = maybe_propose_shared_scene(pregunta, request)
        if proposal is not None:
            update_context("domotica", pregunta)
            return jsonify(proposal)
        shared_scene_response = handle_shared_scene_command(pregunta)
        if shared_scene_response is not None:
            update_context("domotica", pregunta)
            return jsonify(shared_scene_response)

    print(f"   🎯 Delegando streaming a: {plugin_name}")

    if plugin_name in plugins:
        plugin_info = plugins[plugin_name]
        module = plugin_info["module"]

        try:
            planned_response = maybe_handle_plugin_plan(plugin_name, pregunta, request)
            if planned_response is not None:
                update_context(plugin_name, pregunta)
                return jsonify(planned_response)
            if hasattr(module, "handle_stream"):
                update_context(plugin_name, pregunta)
                return Response(
                    stream_with_context(module.handle_stream(pregunta)),
                    content_type="application/x-ndjson; charset=utf-8",
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
    device_public_key = (data.get("device_public_key") or "").strip()

    try:
        if "auth" not in plugins:
            return jsonify({"success": False, "message": "Plugin auth no cargado"}), 500

        module = plugins["auth"]["module"]

        if not hasattr(module, "authenticate"):
            return jsonify({"success": False, "message": "Plugin auth inválido"}), 500

        result = module.authenticate(pin)

        if result:
            clear_auth_failures(request)
            token = issue_session_token(
                device_id=device_id,
                device_name=device_name,
                device_public_key=device_public_key,
            )
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


@app.route("/api/v1/auth/jinnex-watch", methods=["POST"])
def jinnex_watch_auth():
    """Emparejamiento local con audiencia y capacidades fijadas por PEARL."""
    # El puente Jinnex llama directo; lo que entra por el túnel no es local.
    if not is_loopback_request(request) or request.headers.get("CF-Connecting-IP"):
        return jsonify({"success": False, "message": "Ruta disponible sólo en loopback."}), 403

    lockout = auth_lockout_response(request)
    if lockout is not None:
        return lockout
    data, error = json_object_or_error(request)
    if error is not None:
        return error
    allowed = {"pin", "device_id", "device_name", "device_public_key"}
    if set(data) - allowed:
        return jsonify({"success": False, "message": "Campos de emparejamiento no permitidos."}), 400
    pin = str(data.get("pin") or "").strip()
    device_id = str(data.get("device_id") or "").strip()
    device_name = str(data.get("device_name") or "Jarvis Watch").strip()
    public_key = str(data.get("device_public_key") or "").strip()
    if not pin or not device_id or not public_key:
        return jsonify({"success": False, "message": "PIN, dispositivo y clave pública son obligatorios."}), 400
    if JINNEX_WATCH_DEVICE_ALLOWLIST and device_id not in JINNEX_WATCH_DEVICE_ALLOWLIST:
        return jsonify({"success": False, "message": "Este reloj no está autorizado."}), 403
    try:
        module = plugins.get("auth", {}).get("module")
        if module is None or not hasattr(module, "authenticate"):
            return jsonify({"success": False, "message": "Plugin auth no disponible."}), 500
        if not module.authenticate(pin):
            record_auth_failure(request)
            return jsonify({"success": False, "message": "PIN incorrecto."}), 403
        clear_auth_failures(request)
        token = issue_session_token(
            device_id=device_id,
            device_name=device_name,
            device_public_key=public_key,
            audience="jinnex-watch",
            scopes=JINNEX_WATCH_SCOPES,
        )
        session = device_session_store.validate(token) or {}
        return jsonify({
            "success": True,
            "message": "Reloj vinculado.",
            "token": f"Bearer {token}",
            "expires_in": SESSION_TTL_SECONDS,
            "session": session,
        })
    except Exception as exc:
        print(f"Error interno auth Watch: {type(exc).__name__}: {exc}")
        return jsonify({"success": False, "message": "No se pudo vincular el reloj."}), 500


@app.route("/auth/session", methods=["GET"])
@app.route("/api/v1/auth/session", methods=["GET"])
def auth_session():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    token = bearer_token(request)
    if is_master_token(token):
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
    if not token or is_master_token(token):
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


@app.route("/devices/status", methods=["GET"])
def list_domotica_device_statuses():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    module = get_domotica_module()
    if not hasattr(module, "list_device_statuses"):
        return jsonify({"error": "domotica_status_not_supported"}), 501
    return jsonify({"statuses": module.list_device_statuses()})


@app.route("/devices/<device_name>/local-key", methods=["PUT"])
def update_domotica_device_local_key(device_name):
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    data, error = json_object_or_error(request)
    if error is not None:
        return error
    module = get_domotica_module()
    if not hasattr(module, "update_device_local_key"):
        return jsonify({"error": "domotica_relink_not_supported"}), 501
    try:
        return jsonify(module.update_device_local_key(device_name, data.get("local_key") or ""))
    except ValueError as exc:
        status = 404 if str(exc) == "device_not_found" else 400
        return jsonify({"error": str(exc)}), status


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


@app.route("/scene-prompts/pending", methods=["GET"])
@app.route("/api/v1/scene-prompts/pending", methods=["GET"])
def hub_scene_prompts_pending():
    session_context, acceso = scene_prompt_gateway_access(request)
    if acceso is not None:
        return acceso

    return hub_api_response(
        "GET",
        "/api/v1/scene-prompts/pending",
        params=request.args.to_dict(flat=True),
        session_context=session_context,
    )


@app.route("/scene-prompts/<prompt_id>/decision", methods=["POST"])
@app.route("/api/v1/scene-prompts/<prompt_id>/decision", methods=["POST"])
def hub_scene_prompt_decision(prompt_id):
    session_context, acceso = scene_prompt_gateway_access(request)
    if acceso is not None:
        return acceso

    data, error = json_object_or_error(request)
    if error is not None:
        return error
    return hub_api_response(
        "POST",
        f"/api/v1/scene-prompts/{prompt_id}/decision",
        json_data=data,
        session_context=session_context,
    )


@app.route("/actions/pending", methods=["GET"])
@app.route("/api/v1/actions/pending", methods=["GET"])
def pending_action_proposals():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso
    proposals = action_proposal_store.list_pending(action_requester(request))
    return jsonify({
        "status": "success",
        "proposals": [action_proposal_store.public(item) for item in proposals],
    })


@app.route("/nova/complex-event-candidates", methods=["GET"])
@app.route("/api/v1/nova/complex-event-candidates", methods=["GET"])
def nova_complex_event_candidates():
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        return jsonify({"status": "error", "error": "invalid_limit"}), 400
    if not 1 <= limit <= 500:
        return jsonify({"status": "error", "error": "invalid_limit"}), 400
    try:
        candidates = fetch_nova_complex_event_candidates(limit)
    except Exception:
        return jsonify({
            "status": "unavailable",
            "source": "nova",
            "candidate_type": "complex_event",
            "candidates": [],
        }), 503
    return jsonify({
        "status": "ok",
        "source": "nova",
        "candidate_type": "complex_event",
        "count": len(candidates),
        "candidates": candidates,
    })


@app.route("/actions/<proposal_id>/decision", methods=["POST"])
@app.route("/api/v1/actions/<proposal_id>/decision", methods=["POST"])
def decide_action_proposal(proposal_id):
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso
    data, error = json_object_or_error(request)
    if error is not None:
        return error
    payload, status_code = apply_action_decision(
        proposal_id=proposal_id,
        decision=data.get("decision"),
        idempotency_key=data.get("idempotency_key"),
        requester=action_requester(request),
    )
    return jsonify(payload), status_code


@app.route("/health", methods=["GET"])
@app.route("/api/v1/health", methods=["GET"])
def health():
    """Estado del sistema."""
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    return jsonify({
        "status": "online",
        "liveness": True,
        "product": product_identity(),
        "plugins": len(plugins),
        "versions": {name: info["version"] for name, info in plugins.items()},
        "plugin_errors": plugin_errors,
        "scene_memory": shared_scene_memory.summary(),
        "nova_outbox": nova_outbox_health(),
    })


def nova_outbox_health():
    if not NOVA_ENABLED:
        return {"enabled": False}
    bus = app.config.get("NOVA_EVENT_BUS") or _nova_event_bus
    if bus is None:
        return {"enabled": True, "degraded": True, "error": "outbox_not_initialized"}
    try:
        return {"enabled": True, **bus.health_summary()}
    except Exception:
        return {"enabled": True, "degraded": True, "error": "outbox_unavailable"}

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


def start_runtime():
    """Inicializar también la entrega de observaciones pendientes tras reiniciar."""
    load_plugins()
    try:
        bus = get_nova_event_bus()
        if bus is not None:
            atexit.register(bus.close)
    except Exception:
        app.logger.error("No se pudo iniciar la cola de observaciones Nova.")


if __name__ == "__main__":
    start_runtime()
    print("\n🚀 JARVIS CORE iniciado")
    print(f"   🌐 http://localhost:{CORE_PORT}")
    print(f"   📦 Plugins activos: {len(plugins)}\n")
    if CORE_DEBUG:
        app.run(host=CORE_HOST, port=CORE_PORT, debug=True)
    else:
        from waitress import serve

        serve(app, host=CORE_HOST, port=CORE_PORT, threads=8)
