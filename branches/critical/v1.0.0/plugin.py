import requests
import json

VERSION = "v3.0.0"
DESCRIPTION = "Delega tareas pesadas al orquestador de laptop"
TRIGGERS = ["analiza", "evalúa", "investiga", "optimiza", "estrategia", 
            "plan", "proyecto", "sistema", "compara", "recomienda"]

ORCHESTRATOR_URL = "http://jarvis-node.local:5006"

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
                
    except requests.exceptions.Timeout:
        return fallback_local(pregunta, "Timeout conectando con orquestador")
    except requests.exceptions.ConnectionError:
        return fallback_local(pregunta, "Orquestador no disponible")
    except Exception as e:
        return fallback_local(pregunta, str(e))

def fallback_local(pregunta, razon=""):
    """
    Fallback: usa Qwen2.5:0.5b local del G05
    """
    # Aquí llamarías a tu local_ia o responder directamente
    return {
        "respuesta": f"Modo local (fallback). {razon}. Procesando con cerebro edge...",
        "cerebro": "local_ia (fallback)",
        "status": "local_fallback",
        "sugerencia": "Intenta de nuevo cuando estés en casa"
    }

def fallback_local(pregunta, razon=""):
    """
    Fallback: usa Qwen2.5:0.5b local del G05 via local_ia
    """
    try:
        # Llamar al plugin local_ia internamente
        import sys
        sys.path.insert(0, '/data/data/com.termux/files/home/JARVIS_CORE/branches/local_ia/current')
        from plugin import handle as local_handle
        
        resultado = local_handle(pregunta)
        resultado["cerebro"] = "local_ia (fallback)"
        resultado["fallback_reason"] = razon
        return resultado
        
    except Exception as e:
        return {
            "respuesta": f"No disponible. {razon}. Error: {str(e)}",
            "cerebro": "error",
            "status": "failed"
        }
