"""
Plugin LOCAL_IA - IA local real con qwen2.5:0.5b
"""

import os
import requests
import json

NAME = "local_ia"
VERSION = "v1.0.0"
OLLAMA_URL = os.getenv("JARVIS_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("JARVIS_OLLAMA_MODEL", "qwen2.5:0.5b")
DESCRIPTION = f"IA local rápida ({OLLAMA_MODEL})"
TRIGGERS = ["hola", "gracias", "chau", "como", "qué", "cuándo", "dónde", "por qué"]

def can_handle(prompt):
    return True  # Captura todo lo que no capturaron otros plugins

def ndjson_event(event):
    return json.dumps(event, ensure_ascii=False) + "\n"

def iter_json_objects(payload):
    decoder = json.JSONDecoder()
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    elif not isinstance(payload, str):
        payload = str(payload)

    text = payload.strip()
    index = 0

    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        obj, next_index = decoder.raw_decode(text, index)
        yield obj
        index = next_index

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

def handle_stream(prompt):
    yield ndjson_event({
        "event": "meta",
        "status": "streaming",
        "plugin": NAME,
        "model": OLLAMA_MODEL
    })

    try:
        with requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": True},
            timeout=(5, 240),
            stream=True
        ) as response:
            if response.status_code != 200:
                yield ndjson_event({
                    "event": "error",
                    "status": "error",
                    "plugin": NAME,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}"
                })
                return

            full_response = []
            for payload in response.iter_lines(decode_unicode=True):
                if not payload:
                    continue

                for chunk in iter_json_objects(payload):
                    token = chunk.get("response", "")
                    if token:
                        full_response.append(token)
                        yield ndjson_event({
                            "event": "token",
                            "status": "streaming",
                            "plugin": NAME,
                            "response": token
                        })

                    if chunk.get("done"):
                        yield ndjson_event({
                            "event": "done",
                            "status": "success",
                            "plugin": NAME,
                            "model": OLLAMA_MODEL,
                            "response": "".join(full_response)
                        })
                        return
    except requests.exceptions.Timeout:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "plugin": NAME,
            "error": "IA local tardó demasiado. ¿Ollama está corriendo?"
        })
    except Exception as e:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "plugin": NAME,
            "error": str(e)
        })
