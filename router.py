# router.py
import re
import time
import unicodedata
from typing import Dict, List, Optional

# =========================
# CONFIG
# =========================

CONTEXT_TTL = 300  # segundos: 5 minutos de contexto útil

GLOBAL_STOP_WORDS = {
    "stop", "parar", "para", "detener", "detene", "deten", "pausa",
    "silencio", "callate", "corta", "frena"
}

MUSIC_CONTROL_WORDS = {
    "play", "pausa", "reanuda", "reanudar", "continua", "continuar",
    "siguiente", "next", "anterior", "previo", "previous",
    "silencio", "sube el volumen", "baja el volumen"
}

DOMOTICA_WORDS = {
    "domotica": 12,
    "domótica": 12,
    "luz": 10,
    "luces": 10,
    "lampara": 10,
    "lámpara": 10,
    "bombilla": 8,
    "brillo": 8,
    "intensidad": 7,
    "color": 7,
    "rojo": 7,
    "azul": 7,
    "verde": 7,
    "colores": 7,
    "calida": 7,
    "cálido": 7,
    "fria": 7,
    "frío": 7,
    "temperatura": 7,
    "escena": 8,
    "ambiente": 6,
    "automatizacion": 8,
    "automatización": 8,
    "memoria domotica": 10,
    "memoria domótica": 10,
    "patron": 8,
    "patrón": 8,
    "patrones": 8,
    "escenas aprendidas": 10,
    "relax": 5,
    "noche": 5,
    "lectura": 5,
    "ofi": 4,
    "oficina": 4,
    "prender": 8,
    "encender": 8,
    "apagar": 8,
    "enciende": 8,
    "apaga": 8,
    "prende": 8,
    "apaga": 8,
    "deshacer": 8,
    "restaurar": 8,
}

MUSIC_WORDS = {
    "musica": 10,
    "música": 10,
    "reproduce": 10,
    "reproducir": 10,
    "pon": 8,
    "play": 9,
    "pausa": 8,
    "stop": 8,
    "cancion": 8,
    "canción": 8,
    "tema": 6,
    "sonando": 9,
    "reproductor": 8,
    "playlist": 8,
    "album": 6,
    "álbum": 6,
    "artista": 6,
    "banda": 5,
    "lofi": 9,
    "jazz": 8,
    "rock": 7,
    "relajante": 8,
    "relax": 4,
    "spotify": 6,
    "youtube": 6,
}

MUSIC_LOCAL_HINTS = {
    "local": 8,
    "celular": 9,
    "telefono": 9,
    "teléfono": 9,
    "android": 8,
    "aca": 5,
    "acá": 5,
    "este dispositivo": 10,
}

MUSIC_REMOTE_HINTS = {
    "laptop": 9,
    "pc": 8,
    "computadora": 8,
    "notebook": 8,
    "nodo": 7,
    "remoto": 7,
    "alla": 5,
    "allá": 5,
}

SCENE_MANAGEMENT_PHRASES = {
    "aprobar escena",
    "aprueba escena",
    "aproba escena",
    "aprobar patron",
    "aprueba patron",
    "aproba patron",
    "rechazar escena",
    "rechaza escena",
    "rechazar patron",
    "rechaza patron",
    "activar escena",
    "activa escena",
    "ejecutar escena",
    "ejecuta escena",
    "listar escenas",
    "lista escenas",
    "muestra escenas",
    "ver escenas",
    "escenas aprendidas",
    "escenas guardadas",
    "patrones",
    "automatizaciones",
}

LOCAL_IA_WORDS = {
    "pregunta": 4,
    "explica": 6,
    "explicame": 6,
    "explícame": 6,
    "que": 1,
    "qué": 1,
    "como": 2,
    "cómo": 2,
    "por que": 3,
    "por qué": 3,
    "analiza": 6,
    "resume": 6,
    "idea": 3,
    "genera": 6,
    "crea": 7,
    "python": 7,
}

INTERNET_WORDS = {
    "busca": 8,
    "buscar": 8,
    "internet": 8,
    "google": 7,
    "web": 7,
    "noticias": 8,
    "precio": 7,
    "precios": 7,
    "cotizacion": 7,
    "cotización": 7,
    "vuelo": 8,
    "vuelos": 8,
}

CRITICAL_WORDS = {
    "emergencia": 10,
    "urgente": 10,
    "critico": 10,
    "crítico": 10,
    "alarma": 9,
    "alerta": 9,
    "peligro": 10,
    "riesgos": 9,
}

HARDWARE_WORDS = {
    "sistema": 9,
    "bateria": 10,
    "batería": 10,
    "reporte": 9,
    "estado": 10,
    "linterna": 10,
    "torch": 8,
    "flash": 8,
    "vibrar": 8,
    "vibracion": 8,
    "vibración": 8,
    "huella": 8,
    "biometria": 8,
    "biometría": 8,
}

TEST_WORDS = {
    "pregunta": 7,
    "test": 8,
    "prueba": 9,
}

TERMUX_API_WORDS = {
    "termux api": 10,
    "termux:api": 10,
    "api termux": 10,
    "api android": 9,
    "estado api": 8,
    "probar api": 8,
    "reparar api": 9,
    "levantar api": 9,
    "termux-volume": 8,
    "termux-toast": 8,
    "termux-torch": 8,
}

SYSTEM_STATUS_PATTERNS = {
    "estado del sistema",
    "estado general",
    "estado de pearl",
    "estado del core",
    "salud del sistema",
    "diagnostico del sistema",
    "diagnóstico del sistema",
    "diagnostico de pearl",
    "diagnóstico de pearl",
    "plugins disponibles",
    "health",
    "system status",
}

# Para desempates o preferencias base
BASE_PRIORITIES = {
    "test": 0,
    "domotica": 0,
    "music_local": 1,
    "music": 1,
    "local_ia": 1,
    "internet": 0,
    "critical": 0,
    "hardware": 0,
    "termux_api": 0,
    "auth": 0,
}


# =========================
# ESTADO DE CONTEXTO
# =========================

ROUTER_STATE = {
    "last_plugin": None,
    "last_domain": None,
    "last_command": None,
    "last_success_ts": 0.0,
}


# =========================
# UTILS
# =========================

def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def contains_phrase(text: str, phrase: str) -> bool:
    return phrase in text


def add_keyword_scores(text: str, score_map: Dict[str, int], words: Dict[str, int]):
    for word, weight in words.items():
        if contains_phrase(text, normalize_text(word)):
            score_map_score = score_map.get("_tmp", 0)  # dummy para legibilidad
            score_map_score += weight
            score_map["_tmp"] = score_map_score


def compute_keyword_score(text: str, words: Dict[str, int]) -> int:
    score = 0
    for word, weight in words.items():
        if contains_phrase(text, normalize_text(word)):
            score += weight
    return score


def has_any_phrase(text: str, phrases) -> bool:
    return any(contains_phrase(text, normalize_text(phrase)) for phrase in phrases)


def is_scene_management_command(text: str) -> bool:
    return has_any_phrase(text, SCENE_MANAGEMENT_PHRASES)


def is_system_status_request(text: str) -> bool:
    return has_any_phrase(text, SYSTEM_STATUS_PATTERNS)


def has_music_local_hint(text: str) -> bool:
    return has_any_phrase(text, MUSIC_LOCAL_HINTS.keys())


def has_music_remote_hint(text: str) -> bool:
    return has_any_phrase(text, MUSIC_REMOTE_HINTS.keys())


def is_clear_music_request(text: str) -> bool:
    if is_scene_management_command(text):
        return False
    return has_any_phrase(text, MUSIC_WORDS.keys())


def context_is_fresh() -> bool:
    return (time.time() - ROUTER_STATE["last_success_ts"]) <= CONTEXT_TTL


def update_context(plugin_name: str, original_text: str):
    ROUTER_STATE["last_plugin"] = plugin_name
    ROUTER_STATE["last_domain"] = plugin_name
    ROUTER_STATE["last_command"] = original_text
    ROUTER_STATE["last_success_ts"] = time.time()


def get_last_plugin() -> Optional[str]:
    if context_is_fresh():
        return ROUTER_STATE["last_plugin"]
    return None


def is_global_stop(text: str) -> bool:
    return text in GLOBAL_STOP_WORDS


def is_music_control(text: str) -> bool:
    return text in MUSIC_CONTROL_WORDS


def prefer_music_plugin(available_plugins: List[str]) -> Optional[str]:
    last_plugin = get_last_plugin()
    if last_plugin in {"music_local", "music"} and last_plugin in available_plugins:
        return last_plugin

    if "music" in available_plugins:
        return "music"
    if "music_local" in available_plugins:
        return "music_local"

    return None


# =========================
# REGLAS
# =========================

def score_domotica(text: str) -> int:
    score = compute_keyword_score(text, DOMOTICA_WORDS)

    # Reglas fuertes
    if "luz" in text or "lampara" in text or "luces" in text:
        score += 15

    if "domotica" in text and any(x in text for x in ["memoria", "patron", "patrones", "escena", "automatizacion"]):
        score += 18

    # Escenas conocidas
    if ("relax" in text or "noche" in text or "lectura" in text) and (
        "luz" in text or "lampara" in text or "escena" in text or "ambiente" in text
    ):
        score += 12

    return score


def score_music_local(text: str) -> int:
    score = compute_keyword_score(text, MUSIC_WORDS)
    score += compute_keyword_score(text, MUSIC_LOCAL_HINTS)

    # Reglas fuertes
    if "reproduce" in text or "musica" in text or "play" in text:
        score += 10

    # Si menciona lofi/jazz/relajante y no menciona luz, empuja a música
    if any(x in text for x in ["lofi", "jazz", "relajante", "playlist", "cancion", "sonando", "reproductor"]):
        score += 7

    return score


def score_music_remote(text: str) -> int:
    score = compute_keyword_score(text, MUSIC_WORDS)
    score += compute_keyword_score(text, MUSIC_REMOTE_HINTS)

    if any(x in text for x in ["laptop", "pc", "computadora", "notebook", "nodo"]):
        score += 12

    return score


def score_local_ia(text: str) -> int:
    return compute_keyword_score(text, LOCAL_IA_WORDS)


def score_internet(text: str) -> int:
    return compute_keyword_score(text, INTERNET_WORDS)


def score_critical(text: str) -> int:
    return compute_keyword_score(text, CRITICAL_WORDS)

def score_hardware(text: str) -> int:
    return compute_keyword_score(text, HARDWARE_WORDS)

def score_test(text: str) -> int:
    return compute_keyword_score(text, TEST_WORDS)

def score_termux_api(text: str) -> int:
    return compute_keyword_score(text, TERMUX_API_WORDS)

def route_query(text: str, available_plugins: List[str]) -> str:
    """
    Devuelve el nombre del plugin más adecuado.
    available_plugins: lista real de plugins cargados en el core.
    """
    raw_text = text
    text = normalize_text(text)

    if is_system_status_request(text):
        return "core_health"

    if is_scene_management_command(text) and "domotica" in available_plugins:
        return "domotica"

    # -------------------------
    # 1) STOP CONTEXTUAL
    # -------------------------
    if is_global_stop(text):
        music_plugin = prefer_music_plugin(available_plugins)
        if music_plugin:
            return music_plugin

        last_plugin = get_last_plugin()
        if last_plugin in available_plugins:
            return last_plugin

    # Controles exactos de la UI de música. Sin esto, "reanuda",
    # "siguiente" y "anterior" caen por score bajo en local_ia.
    if is_music_control(text):
        music_plugin = prefer_music_plugin(available_plugins)
        if music_plugin:
            return music_plugin

    # Reproduccion simple: prioriza el nodo de musica remoto. Solo cae en
    # music_local si el usuario pide explicitamente el celular/local o si el
    # plugin remoto no esta cargado.
    if is_clear_music_request(text):
        if has_music_local_hint(text) and "music_local" in available_plugins:
            return "music_local"
        if has_music_remote_hint(text) and "music" in available_plugins:
            return "music"
        if "music" in available_plugins:
            return "music"
        if "music_local" in available_plugins:
            return "music_local"

    # -------------------------
    # 2) SCORING
    # -------------------------
    scores = {}

    if "domotica" in available_plugins:
        scores["domotica"] = score_domotica(text) + BASE_PRIORITIES["domotica"]

    if "music_local" in available_plugins:
        scores["music_local"] = score_music_local(text) + BASE_PRIORITIES["music_local"]

    if "music" in available_plugins:
        scores["music"] = score_music_remote(text) + BASE_PRIORITIES["music"]

    if "local_ia" in available_plugins:
        scores["local_ia"] = score_local_ia(text) + BASE_PRIORITIES["local_ia"]

    if "internet" in available_plugins:
        scores["internet"] = score_internet(text) + BASE_PRIORITIES["internet"]

    if "critical" in available_plugins:
        scores["critical"] = score_critical(text) + BASE_PRIORITIES["critical"]
    
    if "hardware" in available_plugins:
        scores["hardware"] = score_hardware(text) + BASE_PRIORITIES["hardware"]

    if "test" in available_plugins:
        scores["test"] = score_test(text) + BASE_PRIORITIES["test"]

    if "termux_api" in available_plugins:
        scores["termux_api"] = score_termux_api(text) + BASE_PRIORITIES["termux_api"]

    # -------------------------
    # 3) REGLAS DE SUPREMACÍA
    # -------------------------
    # Si menciona luz/lámpara, domótica manda
    if any(x in text for x in ["luz", "luces", "lampara", "bombilla"]):
        if "domotica" in scores:
            scores["domotica"] += 20

        # si además decía relax/noche/lectura, casi seguro escena de luz
        if any(x in text for x in ["relax", "noche", "lectura", "calido", "frio", "color"]):
            scores["domotica"] += 15

    # Si claramente pide reproducir música
    if any(x in text for x in ["reproduce", "musica", "play", "playlist", "cancion", "sonando", "reproductor", "lofi", "jazz"]):
        if "music_local" in scores:
            scores["music_local"] += 10
        if "music" in scores:
            scores["music"] += 6

    # Si pide analisis/estrategia, prioriza delegacion pesada sobre estado de hardware.
    if any(x in text for x in ["analiza", "evalua", "investiga", "optimiza", "estrategia", "plan", "proyecto", "compara", "recomienda"]):
        if "critical" in scores:
            scores["critical"] += 20

    # Si explicita dispositivo remoto
    if any(x in text for x in ["laptop", "pc", "computadora", "notebook", "nodo"]):
        if "music" in scores:
            scores["music"] += 20

    # Si explicita local/móvil
    if any(x in text for x in ["celular", "android", "telefono", "aca", "este dispositivo"]):
        if "music_local" in scores:
            scores["music_local"] += 20

    # Termux:API solo debe capturar diagnósticos explícitos del puente Android.
    if "termux" in text and "api" in text:
        if "termux_api" in scores:
            scores["termux_api"] += 25

    if "api" in text and any(x in text for x in ["estado", "probar", "reparar", "levantar", "iniciar"]):
        if "termux_api" in scores:
            scores["termux_api"] += 15

    # -------------------------
    # 4) CONTEXTO EN FRASES AMBIGUAS
    # -------------------------
    # "relax" solo puede ser ambiguo
    if text == "relax" or text == "modo relax" or text == "ambiente relax":
        last_plugin = get_last_plugin()
        if last_plugin in available_plugins:
            return last_plugin
        if "domotica" in available_plugins:
            return "domotica"

    # Si dice "luz relax", debería ir a domótica
    if "luz" in text and "relax" in text and "domotica" in available_plugins:
        return "domotica"

    # -------------------------
    # 5) ELEGIR GANADOR
    # -------------------------
    if scores:
        best_plugin = max(scores, key=scores.get)
        best_score = scores[best_plugin]

        # Si todo da muy bajo, caer en local_ia o comandos
        if best_score <= 5:
            if "local_ia" in available_plugins:
                return "local_ia"

        return best_plugin

    # -------------------------
    # 6) FALLBACK
    # -------------------------
    if "local_ia" in available_plugins:
        return "local_ia"

    # último fallback
    return available_plugins[0] if available_plugins else "local_ia"
