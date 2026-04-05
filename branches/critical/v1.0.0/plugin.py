"""
Plugin CRITICAL - Procesamiento real con laptop (phi3-fast)
"""

import requests

NAME = "critical"
VERSION = "v1.0.0"
DESCRIPTION = "Análisis crítico vía laptop (phi3-fast)"
TRIGGERS = ["analiza", "riesgo", "peligro", "seguridad", "emergencia", "critico", "importante"]

LAPTOP_URL = "http://192.168.100.101:11434/api/generate"
MODEL = "phi3-fast"
TIMEOUT = 60

def can_handle(prompt):
    prompt_lower = prompt.lower()
    return any(keyword in prompt_lower for keyword in TRIGGERS)

def handle(prompt):
    try:
        response = requests.post(
            LAPTOP_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=TIMEOUT
        )
        if response.status_code == 200:
            respuesta = response.json().get("response", "Error en análisis")
            return {'respuesta': respuesta, 'cerebro': NAME}
        return {'respuesta': f"Error: {response.status_code}", 'cerebro': NAME}
    except requests.exceptions.Timeout:
        return {'respuesta': "La laptop tardó demasiado. ¿Está encendida?", 'cerebro': NAME}
    except requests.exceptions.ConnectionError:
        return {'respuesta': "No se pudo conectar con la laptop.", 'cerebro': NAME}
    except Exception as e:
        return {'respuesta': f"Error: {e}", 'cerebro': NAME}
