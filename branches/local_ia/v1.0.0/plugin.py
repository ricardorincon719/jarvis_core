"""
Plugin LOCAL_IA - IA local real con qwen2.5:0.5b
"""

import os
import requests

NAME = "local_ia"
VERSION = "v1.0.0"
OLLAMA_URL = os.getenv("JARVIS_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("JARVIS_OLLAMA_MODEL", "qwen2.5:0.5b")
DESCRIPTION = f"IA local rápida ({OLLAMA_MODEL})"
TRIGGERS = ["hola", "gracias", "chau", "como", "qué", "cuándo", "dónde", "por qué"]

def can_handle(prompt):
    return True  # Captura todo lo que no capturaron otros plugins

def handle(prompt):
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=240
        )
        if response.status_code == 200:
            return {'respuesta': response.json().get("response", "Error"), 'cerebro': NAME}
        return {'respuesta': f"Error: {response.status_code}", 'cerebro': NAME}
    except requests.exceptions.Timeout:
        return {'respuesta': "IA local tardó demasiado. ¿Ollama está corriendo?", 'cerebro': NAME}
    except Exception as e:
        return {'respuesta': f"Error: {e}", 'cerebro': NAME}
