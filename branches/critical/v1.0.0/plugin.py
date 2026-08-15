import requests
import json
import os
from assistant_identity import build_assistant_prompt

VERSION = "v3.0.0"
DESCRIPTION = "Delega tareas pesadas al orquestador de laptop"
TRIGGERS = ["analiza", "evalúa", "investiga", "optimiza", "estrategia", 
            "plan", "proyecto", "sistema", "compara", "recomienda"]

ORCHESTRATOR_URL = os.getenv("JARVIS_ORCHESTRATOR_URL", "http://jarvis-node.local:5006")
OPENROUTER_API_URL = os.getenv(
    "OPENROUTER_API_URL",
    "https://openrouter.ai/api/v1",
).rstrip("/")
OPENROUTER_CHAT_URL = f"{OPENROUTER_API_URL}/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "deepseek/deepseek-v4-flash",
).strip()
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "PEARL HOME").strip()

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

            for payload in response.iter_lines(decode_unicode=False):
                if not payload:
                    continue

                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8", errors="replace")

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
    Fallback: usa primero el plugin local_ia; si no existe, intenta OpenRouter directo.
    """
    plugin_result = fallback_local_plugin(pregunta, razon)
    if plugin_result is not None:
        return plugin_result

    return fallback_openrouter(pregunta, razon)


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

    yield from fallback_openrouter_stream(pregunta, razon)

def _openrouter_headers():
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME
    return headers


def _openrouter_payload(pregunta, stream=False):
    return {
        "model": OPENROUTER_MODEL,
        "messages": [{
            "role": "user",
            "content": build_assistant_prompt(pregunta),
        }],
        "stream": stream,
    }


def _openrouter_error(response):
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("code")
    else:
        message = error
    message = str(message).strip() if message else ""
    suffix = f": {message[:240]}" if message else ""
    return f"OpenRouter HTTP {response.status_code}{suffix}"


def _openrouter_content(payload):
    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict)
        )
    return str(content or "")


def _openrouter_stream_token(payload):
    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content", "") if isinstance(delta, dict) else ""
    return content if isinstance(content, str) else str(content or "")


def fallback_openrouter(pregunta, razon=""):
    if not OPENROUTER_API_KEY:
        return {
            "respuesta": "OpenRouter no está configurado.",
            "cerebro": "local_ia (fallback)",
            "status": "failed",
            "fallback_reason": razon,
        }

    try:
        response = requests.post(
            OPENROUTER_CHAT_URL,
            headers=_openrouter_headers(),
            json=_openrouter_payload(pregunta),
            timeout=(5, 120),
        )
        if response.status_code == 200:
            return {
                "respuesta": conversational_response(_openrouter_content(response.json()) or "Error"),
                "cerebro": "local_ia (fallback)",
                "status": "local_fallback",
                "fallback_reason": razon
            }

        return {
            "respuesta": f"Fallback OpenRouter respondió HTTP {response.status_code}. {razon}",
            "cerebro": "local_ia (fallback)",
            "status": "failed",
            "fallback_reason": razon
        }
    except Exception as e:
        return {
        "respuesta": f"OpenRouter no disponible. {razon}.",
            "cerebro": "error",
            "status": "failed"
        }

def fallback_openrouter_stream(pregunta, razon=""):
    yield ndjson_event({
        "event": "meta",
        "status": "streaming",
        "plugin": "critical",
        "brain": "local_ia (fallback)",
        "fallback_reason": razon
    })

    if not OPENROUTER_API_KEY:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "plugin": "critical",
            "error": "OpenRouter no está configurado.",
        })
        return

    try:
        with requests.post(
            OPENROUTER_CHAT_URL,
            headers=_openrouter_headers(),
            json=_openrouter_payload(pregunta, stream=True),
            timeout=(5, 120),
            stream=True,
        ) as response:
            if response.status_code != 200:
                yield ndjson_event({
                    "event": "error",
                    "status": "error",
                    "plugin": "critical",
                    "error": f"{_openrouter_error(response)}. {razon}",
                })
                return

            full_response = []
            response_model = OPENROUTER_MODEL
            for raw_line in response.iter_lines(decode_unicode=False):
                if isinstance(raw_line, bytes):
                    raw_line = raw_line.decode("utf-8", errors="replace")
                line = (raw_line or "").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    yield ndjson_event({
                        "event": "done",
                        "status": "success",
                        "plugin": "critical",
                        "brain": "local_ia (fallback)",
                        "model": response_model,
                        "response": conversational_response("".join(full_response)),
                        "fallback_reason": razon,
                    })
                    return
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if chunk.get("model"):
                    response_model = chunk["model"]
                if chunk.get("error"):
                    yield ndjson_event({
                        "event": "error",
                        "status": "error",
                        "plugin": "critical",
                        "error": "Error durante el stream de OpenRouter.",
                    })
                    return

                token = _openrouter_stream_token(chunk)
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
                        "model": response_model,
                        "response": conversational_response("".join(full_response)),
                        "fallback_reason": razon
                    })
                    return
            yield ndjson_event({
                "event": "done",
                "status": "success",
                "plugin": "critical",
                "brain": "local_ia (fallback)",
                "model": response_model,
                "response": conversational_response("".join(full_response)),
                "fallback_reason": razon,
            })
    except Exception as e:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "plugin": "critical",
            "error": f"{razon}. Error de OpenRouter: {str(e)[:200]}"
        })
