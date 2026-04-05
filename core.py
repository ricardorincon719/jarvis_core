#!/usr/bin/env python3
"""
JARVIS CORE - Sistema de Plugins Modular
El core solo orquesta, nunca ejecuta comandos peligrosos.
"""

import os
import json
import importlib
import hashlib
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

SECRET_TOKEN = "jarvis_local_123"
app = Flask(__name__)
CORS(app)

# ========== CONFIGURACIÓN ==========
BRANCHES_DIR = Path("branches")
MANIFEST_FILE = Path("plugin_manifest.json")
plugins = {}

# ========== VERIFICACIÓN DE INTEGRIDAD ==========
def verify_plugin_integrity(plugin_path):
    """Verifica hash de los archivos del plugin"""
    integrity_file = plugin_path / "integrity.json"
    if not integrity_file.exists():
        print(f"   ⚠️ Sin archivo integrity.json")
        return True  # Si no hay, se carga igual (modo desarrollo)
    
    with open(integrity_file) as f:
        expected = json.load(f)
    
    for file_name, expected_hash in expected.items():
        file_path = plugin_path / file_name
        if file_path.exists():
            with open(file_path, 'rb') as f:
                actual_hash = hashlib.sha256(f.read()).hexdigest()
            if actual_hash != expected_hash:
                print(f"   ❌ Integridad fallida: {file_name}")
                return False
    return True

# ========== CARGA DE PLUGINS ==========
def load_plugins():
    """Escanea branches/ y carga todos los plugins"""
    if not BRANCHES_DIR.exists():
        BRANCHES_DIR.mkdir(parents=True)
        print("📁 Carpeta branches/ creada")
        return
    
    print("\n🔍 Escaneando plugins...")
    for branch_name in BRANCHES_DIR.iterdir():
        if not branch_name.is_dir() or branch_name.name.startswith('_'):
            continue
        
        plugin_path = branch_name / "current"
        if plugin_path.exists():
            try:
                # Verificar integridad
                if not verify_plugin_integrity(plugin_path):
                    print(f"   ❌ {branch_name}: integridad fallida, omitido")
                    continue
                
                # Cargar módulo
                module = importlib.import_module(f"branches.{branch_name.name}.current.plugin")
                
                if hasattr(module, 'handle'):
                    plugins[branch_name.name] = {
                        'module': module,
                        'version': getattr(module, 'VERSION', 'v0.0.0'),
                        'description': getattr(module, 'DESCRIPTION', 'Sin descripción'),
                        'triggers': getattr(module, 'TRIGGERS', [])
                    }
                    print(f"   ✅ {branch_name.name} v{plugins[branch_name.name]['version']}")
                else:
                    print(f"   ⚠️ {branch_name}: falta función handle()")
                    
            except Exception as e:
                print(f"   ❌ {branch_name}: error al cargar - {e}")
    
    print(f"\n📊 Total plugins cargados: {len(plugins)}")

# ========== RUTAS ==========
@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    auth = request.headers.get("Authorization")

    if auth != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 403
    
    ip = request.remote_addr

    if not ip.startswith("192.168."):
        return jsonify({"error": "Forbidden"}), 403

    """Endpoint principal - delega a plugins según can_handle"""
    data = request.get_json()
    pregunta = data.get('pregunta', '')
    
    if not pregunta:
        return jsonify({'respuesta': 'Mensaje vacío', 'cerebro': 'Core'})
    
    print(f"\n📨 Consulta: {pregunta}")
    
    # Buscar plugin que pueda manejar la consulta
    for name, plugin_info in plugins.items():
        module = plugin_info['module']
        if hasattr(module, 'can_handle') and module.can_handle(pregunta):
            print(f"   🎯 Delegando a: {name}")
            try:
                response = module.handle(pregunta)
                response['plugin'] = name
                response['version'] = plugin_info['version']
                return jsonify(response)
            except Exception as e:
                print(f"   ❌ Error en plugin {name}: {e}")
                return jsonify({
                    'respuesta': f"Error en módulo {name}: {e}",
                    'cerebro': 'Core',
                    'error': str(e)
                })
    
    # Si ningún plugin maneja, respuesta por defecto
    print("   ⚠️ Ningún plugin maneja esta consulta")
    return jsonify({
        'respuesta': "No sé cómo responder a eso. ¿Puedes reformular?",
        'cerebro': 'Core',
        'sugerencia': 'Consulta disponible en: ' + ', '.join(list(plugins.keys()))
    })

@app.route('/ask_auth', methods=['POST'])   # ← ESTE ES NUEVO, SE AGREGA
def ask_auth():
#    auth = request.headers.get("Authorization")

#    if auth != f"Bearer {SECRET_TOKEN}":
#        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    ip = request.remote_addr

    if not ip.startswith("192.168."):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    pin = data.get('pin', '') if data else ''
    
    if 'auth' in plugins:
        module = plugins['auth']['module']
        if hasattr(module, 'authenticate') and module.authenticate(pin):
            return jsonify({'success': True, 'message': 'Acceso concedido, señor.'})
    return jsonify({'success': False, 'message': 'PIN incorrecto.'})


@app.route('/plugins', methods=['GET'])
def list_plugins():
    auth = request.headers.get("Authorization")

    if auth != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 403

    ip = request.remote_addr

    if not ip.startswith("192.168."):
        return jsonify({"error": "Forbidden"}), 403

    """Lista todos los plugins cargados"""
    return jsonify({
        'plugins': [
            {
                'name': name,
                'version': info['version'],
                'description': info['description'],
                'triggers': info['triggers']
            }
            for name, info in plugins.items()
        ],
        'total': len(plugins)
    })

@app.route('/health', methods=['GET'])
def health():
    """Estado del sistema"""
    return jsonify({
        'status': 'online',
        'plugins': len(plugins),
        'versions': {name: info['version'] for name, info in plugins.items()}
    })

@app.route('/battery')
def battery():
    """Obtiene el estado de la batería del celular"""
    try:
        import subprocess, json
        result = subprocess.run(['termux-battery-status'], capture_output=True, text=True)
        if result.returncode == 0:
            bat = json.loads(result.stdout)
            return jsonify({
                'percentage': bat.get('percentage', 0),
                'status': bat.get('status', 'unknown')
            })
        else:
            return jsonify({'percentage': 0, 'status': 'error'})
    except Exception as e:
        print(f"Error obteniendo batería: {e}")
        return jsonify({'percentage': 0, 'status': 'error'})

if __name__ == '__main__':
    load_plugins()
    print(f"\n🚀 JARVIS CORE iniciado")
    print(f"   🌐 http://localhost:5004")
    print(f"   📦 Plugins activos: {len(plugins)}\n")
    app.run(host='0.0.0.0', port=5004, debug=False)
