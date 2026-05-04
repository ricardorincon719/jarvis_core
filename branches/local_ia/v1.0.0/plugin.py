"""
Plugin LOCAL_IA - IA local real con qwen2.5:0.5b
"""

import requests

NAME = "local_ia"
VERSION = "v1.0.0"
DESCRIPTION = "IA local rápida (qwen2.5:0.5b)"
TRIGGERS = ["hola", "gracias", "chau", "como", "qué", "cuándo", "dónde", "por qué"]

def can_handle(prompt):
    return True  # Captura todo lo que no capturaron otros plugins

def handle(prompt):
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "qwen2.5:0.5b", "prompt": prompt, "stream": False},
            timeout=240
        )
        if response.status_code == 200:
            return {'respuesta': response.json().get("response", "Error"), 'cerebro': NAME}
        return {'respuesta': f"Error: {response.status_code}", 'cerebro': NAME}
    except requests.exceptions.Timeout:
        return {'respuesta': "IA local tardó demasiado. ¿Ollama está corriendo?", 'cerebro': NAME}
    except Exception as e:
        return {'respuesta': f"Error: {e}", 'cerebro': NAME}
