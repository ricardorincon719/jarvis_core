#!/usr/bin/env python3
"""
JARVIS CORE - Sistema de Plugins Modular
El core solo orquesta, nunca ejecuta comandos peligrosos.
"""

import json
import importlib
import hashlib
import ipaddress
import socket
from pathlib import Path
from router import route_query, update_context
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

SECRET_TOKEN = "jarvis_local_123"

app = Flask(__name__)
CORS(app)

# ========== CONFIGURACIÓN ==========
BRANCHES_DIR = Path("branches")
MANIFEST_FILE = Path("plugin_manifest.json")
plugins = {}


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
    auth = req.headers.get("Authorization", "").strip()
    return auth == f"Bearer {SECRET_TOKEN}"

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
    auth = req.headers.get("Authorization", "").strip()
    ip = (req.remote_addr or "").strip()

    if auth != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 403

    if not es_ip_local(ip):
        return jsonify({"error": "Forbidden"}), 403

    return None


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
        if file_path.exists():
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

        except Exception as e:
            print(f"   ❌ {branch_name.name}: error al cargar - {e}")

    print(f"\n📊 Total plugins cargados: {len(plugins)}")


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

    data = request.get_json(silent=True) or {}
    pregunta = (data.get("pregunta") or "").strip()

    if not pregunta:
        return jsonify({"respuesta": "Mensaje vacío", "cerebro": "Core"})

    print(f"\n📨 Consulta: {pregunta}")
    print("REMOTE_ADDR:", request.remote_addr)
    print("HOST:", request.host)

    available_plugins = list(plugins.keys())
    plugin_name = route_query(pregunta, available_plugins)

    print(f"   🎯 Delegando a: {plugin_name}")

    if plugin_name in plugins:
        plugin_info = plugins[plugin_name]
        module = plugin_info["module"]

        try:
            response = module.handle(pregunta)

            if not isinstance(response, dict):
                response = {"respuesta": str(response), "cerebro": plugin_name}

            response["plugin"] = plugin_name
            response["version"] = plugin_info["version"]

            # Guarda contexto para comandos como "stop"
            update_context(plugin_name, pregunta)

            return jsonify(response)

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

@app.route("/ask_auth", methods=["POST"])
def ask_auth():
    print("\n=== DEBUG /ask_auth ===")
    print("REMOTE_ADDR:", request.remote_addr)
    print("HOST:", request.host)
    print("AUTH HEADER:", request.headers.get("Authorization"))
    print("JSON:", request.get_json(silent=True))

    if not token_valido(request):
        print("❌ BLOQUEADO POR TOKEN")
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    pin = (data.get("pin") or "").strip()

    print("PIN RECIBIDO:", repr(pin))
    print("TOKEN ESPERADO:", f"Bearer {SECRET_TOKEN}")

    try:
        if "auth" not in plugins:
            print("❌ Plugin auth no cargado")
            return jsonify({"success": False, "message": "Plugin auth no cargado"}), 500

        module = plugins["auth"]["module"]
        print("PLUGIN AUTH:", module)

        if not hasattr(module, "authenticate"):
            print("❌ Plugin auth sin función authenticate()")
            return jsonify({"success": False, "message": "Plugin auth inválido"}), 500

        result = module.authenticate(pin)
        print("RESULTADO authenticate(pin):", result)

        if result:
            print("✅ ACCESO CONCEDIDO")
            return jsonify({"success": True, "message": "Acceso concedido, señor."})

        print("❌ PIN INCORRECTO")
        return jsonify({"success": False, "message": "PIN incorrecto."}), 403

    except Exception as e:
        print(f"❌ ERROR EN /ask_auth: {type(e).__name__}: {e}")
        return jsonify({"success": False, "message": f"Error interno auth: {type(e).__name__}: {e}"}), 500

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


@app.route("/health", methods=["GET"])
def health():
    """Estado del sistema."""
    return jsonify({
        "status": "online",
        "plugins": len(plugins),
        "versions": {name: info["version"] for name, info in plugins.items()},
    })

@app.route("/network", methods=["GET"])
def network():
    """Devuelve la IP LAN actual y URLs útiles para la UI."""
    lan_ip = get_current_lan_ip()
    return jsonify({
        "localhost": "http://127.0.0.1:5004",
        "lan_ip": lan_ip,
        "lan_url": f"http://{lan_ip}:5004",
        "port": 5004
    })

@app.route("/battery", methods=["GET"])
def battery():
    """Obtiene el estado de la batería del celular."""
    acceso = acceso_local_autorizado(request)
    if acceso is not None:
        return acceso

    try:
        import subprocess

        result = subprocess.run(
            ["termux-battery-status"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            bat = json.loads(result.stdout)
            return jsonify({
                "percentage": bat.get("percentage", 0),
                "status": bat.get("status", "unknown"),
            })

        return jsonify({"percentage": 0, "status": "error"})
    except Exception as e:
        print(f"Error obteniendo batería: {e}")
        return jsonify({"percentage": 0, "status": "error"})


if __name__ == "__main__":
    load_plugins()
    print("\n🚀 JARVIS CORE iniciado")
    print("   🌐 http://localhost:5004")
    print(f"   📦 Plugins activos: {len(plugins)}\n")
    app.run(host="0.0.0.0", port=5004, debug=False)
