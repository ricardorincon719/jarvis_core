import requests
import json
import os

VERSION = "v3.0.0"
DESCRIPTION = "Delega tareas pesadas al orquestador de laptop"
TRIGGERS = ["analiza", "evalúa", "investiga", "optimiza", "estrategia", 
            "plan", "proyecto", "sistema", "compara", "recomienda"]

ORCHESTRATOR_URL = os.getenv("JARVIS_ORCHESTRATOR_URL", "http://jarvis-node.local:5006")
OLLAMA_URL = os.getenv("JARVIS_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("JARVIS_OLLAMA_MODEL", "qwen2.5:0.5b")

def can_handle(pregunta):
    return any(t in pregunta.lower() for t in TRIGGERS)

def handle(pregunta):
    try:
        # Intentar delegar a orquestador
        response = requests.post(
            f"{ORCHESTRATOR_URL}/process",
            json={"prompt": pregunta},
            timeout=65  # phi3-fast puede tardar
        )
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("status") == "success":
                return {
                    "respuesta": result["response"],
                    "cerebro": f"orchestrator→{result['brain']}→{result['model']}",
                    "tiempo_ms": result.get("time", 0),
                    "status": "delegated"
                }
            else:
                # Orchestrator respondió pero con error interno
                return fallback_local(pregunta, f"Orchestrator error: {result.get('error')}")

        return fallback_local(pregunta, f"Orchestrator HTTP {response.status_code}")

    except requests.exceptions.Timeout:
        return fallback_local(pregunta, "Timeout conectando con orquestador")
    except requests.exceptions.ConnectionError:
        return fallback_local(pregunta, "Orquestador no disponible")
    except Exception as e:
        return fallback_local(pregunta, str(e))

def fallback_local(pregunta, razon=""):
    """
    Fallback: usa primero el plugin local_ia; si no existe, intenta Ollama directo.
    """
    plugin_result = fallback_local_plugin(pregunta, razon)
    if plugin_result is not None:
        return plugin_result

    return fallback_ollama(pregunta, razon)


def fallback_local_plugin(pregunta, razon=""):
    try:
        from branches.local_ia.current.plugin import handle as local_handle

        resultado = local_handle(pregunta)
        if not isinstance(resultado, dict):
            resultado = {"respuesta": str(resultado)}

        resultado["cerebro"] = "local_ia (fallback)"
        resultado["status"] = resultado.get("status", "local_fallback")
        resultado["fallback_reason"] = razon
        return resultado

    except Exception:
        return None


def fallback_ollama(pregunta, razon=""):
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": pregunta, "stream": False},
            timeout=240
        )
        if response.status_code == 200:
            return {
                "respuesta": response.json().get("response", "Error"),
                "cerebro": "local_ia (fallback)",
                "status": "local_fallback",
                "fallback_reason": razon
            }

        return {
            "respuesta": f"Fallback local respondió HTTP {response.status_code}. {razon}",
            "cerebro": "local_ia (fallback)",
            "status": "failed",
            "fallback_reason": razon
        }
    except Exception as e:
        return {
            "respuesta": f"No disponible. {razon}. Error: {str(e)}",
            "cerebro": "error",
            "status": "failed"
        }
