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

def _as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []

def _format_system_status(data):
    status = data.get("estado_del_sistema")
    if not isinstance(status, dict):
        return None

    hechos = _as_list(status.get("hechos"))
    riesgos = _as_list(status.get("riesgos"))
    acciones = _as_list(status.get("accion_recomendada"))

    parts = []
    if hechos:
        parts.append("Sistema estable: " + " ".join(hechos))
    if riesgos:
        parts.append("Riesgos detectados: " + " ".join(riesgos))
    else:
        parts.append("No veo riesgos activos.")
    if acciones:
        parts.append("Siguiente paso recomendado: " + " ".join(acciones))
    else:
        parts.append("No hace falta acción inmediata.")

    return " ".join(parts)

def conversational_response(text):
    if not isinstance(text, str):
        return str(text)

    clean_text = text.strip()
    if not clean_text:
        return clean_text

    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError:
        return clean_text

    if isinstance(data, dict):
        formatted = _format_system_status(data)
        if formatted:
            return formatted

    return clean_text

def ndjson_event(event):
    return json.dumps(event, ensure_ascii=False) + "\n"

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
                    "respuesta": conversational_response(result["response"]),
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

def handle_stream(pregunta):
    yield ndjson_event({
        "event": "meta",
        "status": "streaming",
        "plugin": "critical",
        "brain": "orchestrator"
    })

    try:
        with requests.post(
            f"{ORCHESTRATOR_URL}/process",
            json={"prompt": pregunta, "stream": True},
            timeout=(5, 240),
            stream=True
        ) as response:
            if response.status_code != 200:
                yield from fallback_local_stream(pregunta, f"Orchestrator HTTP {response.status_code}")
                return

            full_response = []
            buffered_json = False
            streaming_started = False

            for payload in response.iter_lines(decode_unicode=True):
                if not payload:
                    continue

                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("event")

                if event_type == "meta":
                    yield ndjson_event({
                        "event": "meta",
                        "status": "streaming",
                        "plugin": "critical",
                        "brain": event.get("brain", "orchestrator"),
                        "model": event.get("model")
                    })
                    continue

                if event_type == "token":
                    token = event.get("response", "")
                    if not token:
                        continue

                    full_response.append(token)
                    current = "".join(full_response).lstrip()
                    if not streaming_started and current.startswith(("{", "[")):
                        buffered_json = True

                    if not buffered_json:
                        streaming_started = True
                        yield ndjson_event({
                            "event": "token",
                            "status": "streaming",
                            "plugin": "critical",
                            "response": token
                        })
                    continue

                if event_type == "done":
                    final_text = conversational_response(event.get("response") or "".join(full_response))
                    if buffered_json:
                        yield ndjson_event({
                            "event": "token",
                            "status": "streaming",
                            "plugin": "critical",
                            "response": final_text
                        })
                    yield ndjson_event({
                        "event": "done",
                        "status": "success",
                        "plugin": "critical",
                        "brain": event.get("brain", "orchestrator"),
                        "model": event.get("model"),
                        "response": final_text,
                        "time": event.get("time")
                    })
                    return

                if event_type == "error":
                    yield from fallback_local_stream(pregunta, event.get("error", "Error del orquestador"))
                    return

    except requests.exceptions.Timeout:
        yield from fallback_local_stream(pregunta, "Timeout conectando con orquestador")
    except requests.exceptions.ConnectionError:
        yield from fallback_local_stream(pregunta, "Orquestador no disponible")
    except Exception as e:
        yield from fallback_local_stream(pregunta, str(e))

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

        resultado["respuesta"] = conversational_response(resultado.get("respuesta", ""))
        resultado["cerebro"] = "local_ia (fallback)"
        resultado["status"] = resultado.get("status", "local_fallback")
        resultado["fallback_reason"] = razon
        return resultado

    except Exception:
        return None

def fallback_local_stream(pregunta, razon=""):
    try:
        from branches.local_ia.current.plugin import handle_stream as local_stream

        yield ndjson_event({
            "event": "meta",
            "status": "streaming",
            "plugin": "critical",
            "brain": "local_ia (fallback)",
            "fallback_reason": razon
        })
        yield from local_stream(pregunta)
        return
    except Exception:
        pass

    yield from fallback_ollama_stream(pregunta, razon)

def fallback_ollama(pregunta, razon=""):
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": pregunta, "stream": False},
            timeout=240
        )
        if response.status_code == 200:
            return {
                "respuesta": conversational_response(response.json().get("response", "Error")),
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

def fallback_ollama_stream(pregunta, razon=""):
    yield ndjson_event({
        "event": "meta",
        "status": "streaming",
        "plugin": "critical",
        "brain": "local_ia (fallback)",
        "fallback_reason": razon
    })

    try:
        with requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": pregunta, "stream": True},
            timeout=(5, 240),
            stream=True
        ) as response:
            if response.status_code != 200:
                yield ndjson_event({
                    "event": "error",
                    "status": "error",
                    "plugin": "critical",
                    "error": f"Fallback local HTTP {response.status_code}. {razon}"
                })
                return

            full_response = []
            for payload in response.iter_lines(decode_unicode=True):
                if not payload:
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                token = chunk.get("response", "")
                if token:
                    full_response.append(token)
                    yield ndjson_event({
                        "event": "token",
                        "status": "streaming",
                        "plugin": "critical",
                        "response": token
                    })

                if chunk.get("done"):
                    yield ndjson_event({
                        "event": "done",
                        "status": "success",
                        "plugin": "critical",
                        "brain": "local_ia (fallback)",
                        "response": conversational_response("".join(full_response)),
                        "fallback_reason": razon
                    })
                    return
    except Exception as e:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "plugin": "critical",
            "error": f"{razon}. Error: {str(e)}"
        })
