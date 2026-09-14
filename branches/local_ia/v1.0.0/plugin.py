"""Plugin LOCAL_IA - IA de PEARL HOME mediante OpenRouter."""

import json
import os
import re
import unicodedata
import uuid

import requests

from assistant_identity import build_assistant_prompt


NAME = "local_ia"
VERSION = "v2.1.0"
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
try:
    OPENROUTER_TIMEOUT_SECONDS = float(
        os.getenv("OPENROUTER_TIMEOUT_SECONDS", "120")
    )
except ValueError:
    OPENROUTER_TIMEOUT_SECONDS = 120.0
NOVA_BRIDGE_ENABLED = os.getenv(
    "PEARL_NOVA_ENABLED",
    "false",
).lower() in {"1", "true", "yes", "on"}
NOVA_BRIDGE_URL = os.getenv(
    "PEARL_NOVA_URL",
    "http://127.0.0.1:5010",
).rstrip("/")
NOVA_SESSION_ID = os.getenv(
    "PEARL_NOVA_SESSION_ID",
    "pearl:console:user:ricardo",
).strip()
try:
    NOVA_TIMEOUT_SECONDS = float(os.getenv("PEARL_NOVA_TIMEOUT_SECONDS", "120"))
except ValueError:
    NOVA_TIMEOUT_SECONDS = 120.0

DESCRIPTION = (
    "Nova mediante Jinnex Next (OpenRouter como respaldo)"
    if NOVA_BRIDGE_ENABLED
    else f"IA mediante OpenRouter ({OPENROUTER_MODEL})"
)
TRIGGERS = ["hola", "gracias", "chau", "como", "qué", "cuándo", "dónde", "por qué"]


def can_handle(prompt):
    return True


def _headers():
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME
    return headers


def _payload(prompt, stream=False):
    return {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": build_assistant_prompt(prompt),
            }
        ],
        "stream": stream,
    }


def _not_configured():
    return {
        "respuesta": (
            "OpenRouter no está configurado. "
            "Define OPENROUTER_API_KEY en el archivo .env."
        ),
        "cerebro": NAME,
        "status": "not_configured",
        "model": OPENROUTER_MODEL,
    }


def _response_error(response):
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
    if message:
        message = message[:240]
        return f"OpenRouter HTTP {response.status_code}: {message}"
    return f"OpenRouter HTTP {response.status_code}"


def _content(payload):
    if not isinstance(payload, dict):
        return ""

    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""

    message = choices[0].get("message") or {}
    value = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(value, str):
        return value

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "".join(parts)

    return str(value) if value else ""


def _is_codex_addressed(prompt):
    normalized = unicodedata.normalize("NFKD", str(prompt).casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).strip()
    return re.match(r"^codex\b", normalized) is not None


def _codex_bridge_error(message):
    return {
        "respuesta": message,
        "cerebro": "codex",
        "status": "failed",
        "model": "codex",
        "provider": "jinnex-next",
    }


def _jinnex_query(prompt):
    if not NOVA_BRIDGE_ENABLED:
        if _is_codex_addressed(prompt):
            return _codex_bridge_error(
                "Codex requiere el puente de Jinnex Next, pero no está habilitado."
            )
        return None
    try:
        from flask import g, has_request_context
        authorization = getattr(g, "jinnex_device_authorization", "") if has_request_context() else ""
        body = {"message": prompt, "event_id": "pearl-chat-" + uuid.uuid4().hex}
        if not authorization:
            body["session_id"] = NOVA_SESSION_ID
        response = requests.post(
            f"{NOVA_BRIDGE_URL}/v1/query", json=body,
            headers={"Authorization": authorization} if authorization else {},
            timeout=(2, NOVA_TIMEOUT_SECONDS),
        )
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        if response.status_code != 200:
            route = payload.get("route") if isinstance(payload, dict) else {}
            assistant = route.get("assistant") if isinstance(route, dict) else None
            if assistant == "codex" or _is_codex_addressed(prompt):
                error = payload.get("error") if isinstance(payload, dict) else {}
                message = error.get("message") if isinstance(error, dict) else None
                return _codex_bridge_error(
                    str(message or "Jinnex Next no pudo ejecutar la consulta de Codex.")
                )
            return None
        if not isinstance(payload, dict) or payload.get("status") != "succeeded":
            return None
        output = payload.get("output") or {}
        route = payload.get("route") or {}
        assistant = route.get("assistant", "nova") if isinstance(route, dict) else "nova"
        if assistant == "codex":
            answer = output.get("response") if isinstance(output, dict) else None
            model = output.get("version", "codex") if isinstance(output, dict) else "codex"
        else:
            answer = output.get("text") if isinstance(output, dict) else None
            model = "nova-2.0.1"
        if not isinstance(answer, str) or not answer.strip():
            return None
        proposal = output.get("integrations", {}).get("jinnex_memory_write", {})
        public_proposal = None
        if isinstance(proposal, dict) and proposal.get("status") == "confirmation_required":
            operation_id = str(proposal.get("request_id") or "")
            public_proposal = {"operation_id": operation_id, "status": "confirmation_required",
                               "summary": str(proposal.get("summary") or "Guardar memoria en Jarvis")}
            if authorization:
                answer += (f"\n\nPropuesta pendiente: {public_proposal['summary']}\n"
                           f"/confirmar_memoria {operation_id} o /rechazar_memoria {operation_id}")
            else:
                answer += "\nLa propuesta está pendiente. Usa una sesión de dispositivo para proponer y confirmar memoria desde PEARL."
        return {
            "respuesta": answer.strip(),
            "memory_proposal": public_proposal,
            "cerebro": assistant,
            "status": "success",
            "model": model,
            "provider": "jinnex-next",
            "intent": route.get("action") if isinstance(route, dict) else None,
        }
    except (requests.exceptions.RequestException, TypeError, ValueError):
        if _is_codex_addressed(prompt):
            return _codex_bridge_error(
                "No fue posible conectar con Codex mediante Jinnex Next."
            )
        return None


def _stream_token(payload):
    if not isinstance(payload, dict):
        return ""

    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""

    delta = choices[0].get("delta") or {}
    value = delta.get("content", "") if isinstance(delta, dict) else ""
    return value if isinstance(value, str) else str(value or "")


def _error_event(message):
    return json.dumps(
        {
            "event": "error",
            "status": "error",
            "plugin": NAME,
            "model": OPENROUTER_MODEL,
            "error": message,
        },
        ensure_ascii=False,
    ) + "\n"


def _done_event(response, model=None, status="success", memory_proposal=None):
    event = {
        "event": "done",
        "status": status,
        "plugin": NAME,
        "model": model or OPENROUTER_MODEL,
        "response": response,
    }
    if memory_proposal is not None:
        event["memory_proposal"] = memory_proposal
    return json.dumps(
        event,
        ensure_ascii=False,
    ) + "\n"


def handle(prompt):
    jinnex_response = _jinnex_query(prompt)
    if jinnex_response is not None:
        return jinnex_response

    if not OPENROUTER_API_KEY:
        return _not_configured()

    try:
        response = requests.post(
            OPENROUTER_CHAT_URL,
            headers=_headers(),
            json=_payload(prompt),
            timeout=(5, OPENROUTER_TIMEOUT_SECONDS),
        )
        if response.status_code != 200:
            return {
                "respuesta": _response_error(response),
                "cerebro": NAME,
                "status": "failed",
                "model": OPENROUTER_MODEL,
            }

        try:
            answer = _content(response.json()).strip()
        except (TypeError, ValueError):
            answer = ""

        if not answer:
            answer = "OpenRouter no devolvió una respuesta."
        return {
            "respuesta": answer,
            "cerebro": NAME,
            "status": "success",
            "model": OPENROUTER_MODEL,
        }
    except requests.exceptions.Timeout:
        return {
            "respuesta": "OpenRouter tardó demasiado en responder.",
            "cerebro": NAME,
            "status": "timeout",
            "model": OPENROUTER_MODEL,
        }
    except requests.exceptions.ConnectionError:
        return {
            "respuesta": "No se pudo conectar con OpenRouter.",
            "cerebro": NAME,
            "status": "failed",
            "model": OPENROUTER_MODEL,
        }
    except requests.exceptions.RequestException:
        return {
            "respuesta": "Error de red al consultar OpenRouter.",
            "cerebro": NAME,
            "status": "failed",
            "model": OPENROUTER_MODEL,
        }
    except Exception:
        return {
            "respuesta": "Error interno al consultar OpenRouter.",
            "cerebro": NAME,
            "status": "failed",
            "model": OPENROUTER_MODEL,
        }


def handle_stream(prompt):
    jinnex_response = _jinnex_query(prompt)
    if jinnex_response is not None:
        answer = jinnex_response["respuesta"]
        yield json.dumps(
            {
                "event": "meta",
                "status": "streaming",
                "plugin": NAME,
                "model": jinnex_response["model"],
            },
            ensure_ascii=False,
        ) + "\n"
        yield json.dumps(
            {
                "event": "token",
                "status": "streaming",
                "plugin": NAME,
                "response": answer,
            },
            ensure_ascii=False,
        ) + "\n"
        yield _done_event(
            answer,
            jinnex_response["model"],
            jinnex_response["status"],
            memory_proposal=jinnex_response.get("memory_proposal"),
        )
        return

    yield json.dumps(
        {
            "event": "meta",
            "status": "streaming",
            "plugin": NAME,
            "model": OPENROUTER_MODEL,
        },
        ensure_ascii=False,
    ) + "\n"

    if not OPENROUTER_API_KEY:
        yield _error_event(
            "OpenRouter no está configurado. "
            "Define OPENROUTER_API_KEY en el archivo .env."
        )
        return

    try:
        with requests.post(
            OPENROUTER_CHAT_URL,
            headers=_headers(),
            json=_payload(prompt, stream=True),
            timeout=(5, OPENROUTER_TIMEOUT_SECONDS),
            stream=True,
        ) as response:
            if response.status_code != 200:
                yield _error_event(_response_error(response))
                return

            full_response = []
            response_model = OPENROUTER_MODEL

            for raw_line in response.iter_lines(decode_unicode=False):
                if isinstance(raw_line, bytes):
                    raw_line = raw_line.decode("utf-8", errors="replace")
                line = (raw_line or "").strip()

                # OpenRouter puede enviar comentarios SSE para mantener viva la conexión.
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    yield _done_event("".join(full_response), response_model)
                    return

                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if payload.get("model"):
                    response_model = payload["model"]

                if payload.get("error"):
                    error = payload["error"]
                    message = (
                        error.get("message")
                        if isinstance(error, dict)
                        else str(error)
                    )
                    yield _error_event(
                        f"OpenRouter: {str(message or 'error')[:240]}"
                    )
                    return

                token = _stream_token(payload)
                if token:
                    full_response.append(token)
                    yield json.dumps(
                        {
                            "event": "token",
                            "status": "streaming",
                            "plugin": NAME,
                            "response": token,
                        },
                        ensure_ascii=False,
                    ) + "\n"

            yield _done_event("".join(full_response), response_model)
    except requests.exceptions.Timeout:
        yield _error_event("OpenRouter tardó demasiado en responder.")
    except requests.exceptions.ConnectionError:
        yield _error_event("No se pudo conectar con OpenRouter.")
    except requests.exceptions.RequestException:
        yield _error_event("Error de red al consultar OpenRouter.")
    except Exception:
        yield _error_event("Error interno al consultar OpenRouter.")
