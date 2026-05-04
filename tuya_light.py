VERSION = "3.0.0"
DESCRIPTION = "Control robusto y funcional de lámpara Tuya local con escenas, sliders, restore/undo, cache de IP y confirmación"
TRIGGERS = [
    "luz", "lampara", "lámpara", "cuarto",
    "encender", "prender", "apagar",
    "lectura", "relax", "noche", "normal",
    "calido", "cálido", "frio", "frío",
    "temperatura", "brillo",
    "restaurar", "restaura", "deshacer",
    "como estaba", "cómo estaba",
    "como estaba antes", "cómo estaba antes",
    "ultimo estado", "último estado"
]

import json
import re
import time
import threading
from pathlib import Path

import tinytuya

# =========================================================
# CONFIG
# =========================================================
DEVICE_ID = "3483408310521cf4c753"
LOCAL_KEY = "k~)0B|~.=~[(U!p@"
DEFAULT_IP = "192.168.100.100"
MAC = "10:52:1c:f4:c7:53"
TUYA_VERSION = 3.3

CACHE_FILE = Path(__file__).resolve().parent / "device_cache.json"
DEVICE_LOCK = threading.Lock()

# DPS Steck / Tuya
DPS_SWITCH = "20"
DPS_MODE = "21"
DPS_BRIGHT = "22"
DPS_TEMP = "23"
DPS_COLOR = "24"

# Ajustes de transporte / confirmación
SOCKET_TIMEOUT = 3
SOCKET_RETRY_LIMIT = 2
CONFIRM_RETRIES = 1      # 1 = baja latencia; si quieres más seguridad, sube a 2
CONFIRM_DELAY = 0.45     # mantener bajo para UX rápida
DISCOVERY_TIMEOUT = 8

# Rangos Tuya (ajusta si luego detectas que tu modelo usa otro)
BRIGHT_MIN = 10
BRIGHT_MAX = 1000
TEMP_MIN = 0
TEMP_MAX = 1000

# Escenas
SCENE_NORMAL = {"switch": True, "mode": "white", "brightness": 800, "temp": 650}
SCENE_LECTURA = {"switch": True, "mode": "white", "brightness": 1000, "temp": 850}
SCENE_RELAX = {"switch": True, "mode": "white", "brightness": 350, "temp": 150}
SCENE_NOCHE = {"switch": True, "mode": "white", "brightness": 80, "temp": 60}

# Presets directos
PRESET_CALIDO = {"switch": True, "mode": "white", "temp": 150}
PRESET_FRIO = {"switch": True, "mode": "white", "temp": 850}
PRESET_NORMAL = SCENE_NORMAL.copy()


# =========================================================
# LOG
# =========================================================
def log(msg, rid=None):
    prefix = f"[SteckLight][{rid}]" if rid else "[SteckLight]"
    print(f"{prefix} {msg}")


# =========================================================
# CACHE
# =========================================================
def load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            log(f"Error leyendo cache: {e}")
    return {}


def save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Error guardando cache: {e}")


def get_cached_ip():
    cache = load_cache()
    return cache.get("ip", DEFAULT_IP)


def normalize_state_from_status(status_data):
    if not isinstance(status_data, dict):
        return None
    dps = status_data.get("dps", {})
    if not isinstance(dps, dict):
        return None

    return {
        "switch": bool(dps.get(DPS_SWITCH)) if dps.get(DPS_SWITCH) is not None else None,
        "mode": dps.get(DPS_MODE),
        "brightness": dps.get(DPS_BRIGHT),
        "temp": dps.get(DPS_TEMP),
        "color": dps.get(DPS_COLOR),
        "updated_at": int(time.time())
    }


def compare_states(a, b):
    if not a or not b:
        return False
    aa = {k: v for k, v in a.items() if k != "updated_at"}
    bb = {k: v for k, v in b.items() if k != "updated_at"}
    return aa == bb


def push_previous_state_if_needed(cache, new_state):
    current_state = cache.get("current_state")
    if current_state and new_state and not compare_states(current_state, new_state):
        cache["previous_state"] = current_state


def update_cache_with_state(ip, status_data=None, state_override=None):
    cache = load_cache()
    cache["ip"] = ip
    cache["updated_at"] = int(time.time())
    cache["mac"] = MAC.lower()

    new_state = state_override or normalize_state_from_status(status_data)
    if new_state:
        push_previous_state_if_needed(cache, new_state)
        cache["current_state"] = new_state

        # compatibilidad / fallback
        cache["last_switch"] = new_state.get("switch")
        cache["last_mode"] = new_state.get("mode")
        cache["last_brightness"] = new_state.get("brightness")
        cache["last_temp"] = new_state.get("temp")
        cache["last_color"] = new_state.get("color")

    save_cache(cache)


def save_previous_from_current():
    cache = load_cache()
    current_state = cache.get("current_state")
    if current_state:
        cache["previous_state"] = current_state
        save_cache(cache)


def get_cached_current_state():
    cache = load_cache()
    state = cache.get("current_state")
    if state:
        return state

    fallback = {
        "switch": cache.get("last_switch"),
        "mode": cache.get("last_mode"),
        "brightness": cache.get("last_brightness"),
        "temp": cache.get("last_temp"),
        "color": cache.get("last_color"),
        "updated_at": int(time.time())
    }
    if any(v is not None for v in fallback.values()):
        return fallback
    return None


def get_cached_previous_state():
    cache = load_cache()
    return cache.get("previous_state")


# =========================================================
# DEVICE / STATUS
# =========================================================
def build_device(ip):
    d = tinytuya.BulbDevice(DEVICE_ID, ip, LOCAL_KEY)
    d.set_version(TUYA_VERSION)
    d.set_socketPersistent(False)
    d.set_socketNODELAY(True)
    d.set_socketRetryLimit(SOCKET_RETRY_LIMIT)
    d.set_socketTimeout(SOCKET_TIMEOUT)
    return d


def safe_status(device, rid=None):
    try:
        st = device.status()
        log(f"status() => {st}", rid)
        return st
    except Exception as e:
        log(f"status() falló: {type(e).__name__}: {repr(e)}", rid)
        return None


def is_valid_status(status_data):
    if not isinstance(status_data, dict):
        return False
    if status_data.get("Err") is not None:
        return False
    dps = status_data.get("dps")
    return isinstance(dps, dict)


def get_dps(status_data):
    if not isinstance(status_data, dict):
        return {}
    dps = status_data.get("dps", {})
    return dps if isinstance(dps, dict) else {}


def extract_switch_state(status_data):
    value = get_dps(status_data).get(DPS_SWITCH)
    return None if value is None else bool(value)


def extract_mode(status_data):
    return get_dps(status_data).get(DPS_MODE)


def extract_brightness(status_data):
    return get_dps(status_data).get(DPS_BRIGHT)


def extract_temp(status_data):
    return get_dps(status_data).get(DPS_TEMP)


def extract_color(status_data):
    return get_dps(status_data).get(DPS_COLOR)


def discover_ip(rid=None):
    log("Intentando redescubrir IP local...", rid)
    try:
        scanned = tinytuya.deviceScan(False, DISCOVERY_TIMEOUT)
        log(f"deviceScan() => {scanned}", rid)

        if isinstance(scanned, dict):
            for ip, info in scanned.items():
                if not isinstance(info, dict):
                    continue
                gwid = info.get("gwId") or info.get("id")
                if gwid == DEVICE_ID:
                    log(f"IP redescubierta para {DEVICE_ID}: {ip}", rid)
                    return ip
    except Exception as e:
        log(f"deviceScan() falló: {e}", rid)

    log("No se pudo redescubrir IP; usando cache/default", rid)
    return get_cached_ip()


def get_working_device(force_discovery=False, rid=None):
    candidates = []

    if force_discovery:
        discovered_ip = discover_ip(rid)
        if discovered_ip:
            candidates.append(discovered_ip)

    cached_ip = get_cached_ip()
    if cached_ip not in candidates:
        candidates.append(cached_ip)

    if DEFAULT_IP not in candidates:
        candidates.append(DEFAULT_IP)

    last_error = None

    for ip in candidates:
        try:
            log(f"Probando IP: {ip}", rid)
            d = build_device(ip)
            st = safe_status(d, rid)

            if is_valid_status(st):
                update_cache_with_state(ip, st)
                log(f"IP válida: {ip}", rid)
                return d, ip, st

            if isinstance(st, dict) and st.get("Err") is not None:
                last_error = f"tuya_err_{st.get('Err')}"
            else:
                last_error = "status_none"

            log(f"IP descartada {ip}: {st}", rid)

        except Exception as e:
            last_error = e
            log(f"Error probando IP {ip}: {e}", rid)

    raise RuntimeError(f"No se pudo conectar a la lámpara. Último error: {last_error}")


# =========================================================
# HELPERS UX / CONVERSIÓN
# =========================================================
def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, int(value)))


def percent_to_brightness(percent):
    percent = clamp(percent, 0, 100)
    if percent == 0:
        return BRIGHT_MIN
    return int(BRIGHT_MIN + ((BRIGHT_MAX - BRIGHT_MIN) * (percent / 100.0)))


def percent_to_temp(percent):
    percent = clamp(percent, 0, 100)
    return int(TEMP_MIN + ((TEMP_MAX - TEMP_MIN) * (percent / 100.0)))


def snapshot_from_scene(scene, base_state=None):
    state = dict(base_state or {})
    state.update(scene)
    state["updated_at"] = int(time.time())
    return state


def build_expected_from_state_block(state_block, include_color=True):
    if not state_block or not isinstance(state_block, dict):
        return {}

    expected = {}

    if state_block.get("switch") is not None:
        expected["switch"] = bool(state_block.get("switch"))

    if state_block.get("mode") is not None:
        expected["mode"] = state_block.get("mode")

    if state_block.get("brightness") is not None:
        expected["brightness"] = int(state_block.get("brightness"))

    if state_block.get("mode") == "white" and state_block.get("temp") is not None:
        expected["temp"] = int(state_block.get("temp"))

    if include_color and state_block.get("mode") == "colour" and state_block.get("color") is not None:
        expected["color"] = str(state_block.get("color"))

    return expected


def explain_expected(expected):
    if not expected:
        return "sin validación específica"
    return ", ".join(f"{k}={v}" for k, v in expected.items())


def color_matches(actual, expected):
    if actual is None or expected is None:
        return False
    return str(actual).lower() == str(expected).lower()


def expected_matches(status_data, expected):
    if not expected:
        return True

    ok = True
    if "switch" in expected:
        ok = ok and (extract_switch_state(status_data) is expected["switch"])
    if "mode" in expected:
        ok = ok and (extract_mode(status_data) == expected["mode"])
    if "brightness" in expected:
        ok = ok and (int(extract_brightness(status_data)) == int(expected["brightness"]))
    if "temp" in expected:
        ok = ok and (int(extract_temp(status_data)) == int(expected["temp"]))
    if "color" in expected:
        ok = ok and color_matches(extract_color(status_data), expected["color"])
    return ok


def confirm_expected_state(device, expected=None, retries=CONFIRM_RETRIES, delay=CONFIRM_DELAY, rid=None):
    last_status = None

    for i in range(retries):
        time.sleep(delay)
        st = safe_status(device, rid)
        last_status = st

        if st is None or not is_valid_status(st):
            log(f"Confirmación {i + 1}/{retries}: transport_error", rid)
            continue

        matched = expected_matches(st, expected)
        log(f"Confirmación {i + 1}/{retries}: matched={matched} esperado=({explain_expected(expected)})", rid)

        if matched:
            return True, st, "matched"

    if last_status is None:
        return False, None, "transport_error"

    return False, last_status, "mismatch"


def classify_result(result):
    if result["ok"]:
        return "confirmed"
    if result["sent"] and result["failure_reason"] == "mismatch":
        return "sent_but_unconfirmed"
    if result["sent"] and result["failure_reason"] == "transport_error":
        return "transport_error"
    return "failed"


def format_response(success_msg, fail_msg, result):
    if result["classification"] == "confirmed":
        return {
            "respuesta": f"{success_msg} (confirmado, IP {result['ip']})",
            "cerebro": "SteckLight",
            "debug": result
        }

    if result["classification"] == "sent_but_unconfirmed":
        return {
            "respuesta": f"{fail_msg}: comando enviado pero no confirmó exactamente el estado esperado (IP {result['ip']})",
            "cerebro": "SteckLight",
            "debug": result
        }

    if result["classification"] == "transport_error":
        return {
            "respuesta": f"Error de transporte/control local (IP {result['ip']}): {result['error']}",
            "cerebro": "SteckLight",
            "debug": result
        }

    return {
        "respuesta": f"Error controlando la lámpara: {result['error']}",
        "cerebro": "SteckLight",
        "debug": result
    }


# =========================================================
# APLICACIÓN DE ESTADOS
# =========================================================
def run_scene(device, scene, rid=None):
    target_mode = scene.get("mode")

    if target_mode:
        log(f"Aplicando modo: {target_mode}", rid)
        device.set_mode(target_mode)
        time.sleep(0.20)

    if "switch" in scene:
        if scene["switch"]:
            log("Aplicando switch ON", rid)
            device.turn_on()
        else:
            log("Aplicando switch OFF", rid)
            device.turn_off()
        time.sleep(0.20)

    if target_mode == "white":
        if "brightness" in scene and scene["brightness"] is not None:
            log(f"Aplicando brightness: {scene['brightness']}", rid)
            device.set_brightness(int(scene["brightness"]))
            time.sleep(0.20)

        if "temp" in scene and scene["temp"] is not None:
            log(f"Aplicando temp: {scene['temp']}", rid)
            device.set_colourtemp(int(scene["temp"]))
            time.sleep(0.20)

    elif target_mode == "colour":
        if "color" in scene and scene["color"]:
            color_name = scene["color"]
            rgb_map = {
                "red": (255, 0, 0),
                "blue": (0, 0, 255),
                "green": (0, 255, 0),
            }
            if color_name in rgb_map:
                r, g, b = rgb_map[color_name]
                log(f"Aplicando color RGB: {r},{g},{b}", rid)
                device.set_colour(r, g, b)
                time.sleep(0.20)

        if "brightness" in scene and scene["brightness"] is not None:
            log(f"Aplicando brightness en colour: {scene['brightness']}", rid)
            device.set_brightness(int(scene["brightness"]))
            time.sleep(0.20)


def apply_snapshot(device, state_block, rid=None):
    if not state_block:
        return

    target_mode = state_block.get("mode")
    target_switch = state_block.get("switch")
    target_brightness = state_block.get("brightness")
    target_temp = state_block.get("temp")
    target_color = state_block.get("color")

    if target_mode:
        log(f"Restaurando modo: {target_mode}", rid)
        device.set_mode(target_mode)
        time.sleep(0.20)

    if target_switch is not None:
        if bool(target_switch):
            log("Restaurando switch ON", rid)
            device.turn_on()
        else:
            log("Restaurando switch OFF", rid)
            device.turn_off()
        time.sleep(0.20)

    if target_mode == "white":
        if target_brightness is not None:
            log(f"Restaurando brightness: {target_brightness}", rid)
            device.set_brightness(int(target_brightness))
            time.sleep(0.20)

        if target_temp is not None:
            log(f"Restaurando temp: {target_temp}", rid)
            device.set_colourtemp(int(target_temp))
            time.sleep(0.20)

    elif target_mode == "colour":
        if target_color:
            color_map = {
                "000003e803e8": (255, 0, 0),
                "00f003e803e8": (0, 0, 255),
                "007803e803e8": (0, 255, 0),
            }
            rgb = color_map.get(str(target_color))
            if rgb:
                log(f"Restaurando color RGB: {rgb}", rid)
                device.set_colour(*rgb)
                time.sleep(0.20)

        if target_brightness is not None:
            log(f"Restaurando brightness en colour: {target_brightness}", rid)
            device.set_brightness(int(target_brightness))
            time.sleep(0.20)


# =========================================================
# MOTOR DE EJECUCIÓN
# =========================================================
def execute_with_confirmation(action_fn, expected=None, pre_mode=None, predicted_state=None, rid=None):
    try:
        device, ip, before = get_working_device(force_discovery=False, rid=rid)
    except Exception as e:
        log(f"Primer intento de conexión falló: {e}", rid)
        device, ip, before = get_working_device(force_discovery=True, rid=rid)

    result = {
        "ok": False,
        "sent": False,
        "confirmed": False,
        "classification": "failed",
        "failure_reason": None,
        "ip": ip,
        "expected": expected,
        "state_before": before,
        "state_after": None,
        "error": None,
    }

    try:
        # Guardar previous_state antes de modificar
        if is_valid_status(before):
            update_cache_with_state(ip, before)

        if pre_mode is not None:
            log(f"Seteando modo previo: {pre_mode}", rid)
            device.set_mode(pre_mode)
            time.sleep(0.20)

        log("Enviando comando...", rid)
        action_fn(device)
        result["sent"] = True

    except Exception as e:
        result["error"] = f"send_failed: {e}"
        result["failure_reason"] = "transport_error"
        result["classification"] = classify_result(result)
        return result

    confirmed, after, reason = confirm_expected_state(
        device,
        expected=expected,
        retries=CONFIRM_RETRIES,
        delay=CONFIRM_DELAY,
        rid=rid
    )

    result["state_after"] = after
    result["confirmed"] = confirmed
    result["ok"] = confirmed
    result["failure_reason"] = None if confirmed else reason
    result["classification"] = classify_result(result)

    if after is not None:
        update_cache_with_state(ip, after)
    elif predicted_state is not None and result["sent"]:
        # fallback útil si se envió bien pero status no volvió
        update_cache_with_state(ip, state_override=predicted_state)

    if result["sent"] and not result["confirmed"] and reason == "transport_error":
        result["error"] = "transport_error_after_send"

        try:
            log("Fallo de transporte tras envío; redescubriendo IP...", rid)
            device, ip, _ = get_working_device(force_discovery=True, rid=rid)
            result["ip"] = ip

            if pre_mode is not None:
                log(f"Reaplicando modo previo: {pre_mode}", rid)
                device.set_mode(pre_mode)
                time.sleep(0.20)

            log("Reenviando comando tras redescubrimiento...", rid)
            action_fn(device)

            confirmed, after, reason = confirm_expected_state(
                device,
                expected=expected,
                retries=CONFIRM_RETRIES,
                delay=CONFIRM_DELAY,
                rid=rid
            )

            result["state_after"] = after
            result["confirmed"] = confirmed
            result["ok"] = confirmed
            result["failure_reason"] = None if confirmed else reason
            result["classification"] = classify_result(result)

            if after is not None:
                update_cache_with_state(ip, after)
            elif predicted_state is not None and result["sent"]:
                update_cache_with_state(ip, state_override=predicted_state)

            if confirmed:
                result["error"] = None

        except Exception as e:
            result["error"] = f"retry_failed: {e}"
            result["failure_reason"] = "transport_error"
            result["classification"] = classify_result(result)

    elif result["sent"] and not result["confirmed"] and reason == "mismatch":
        result["error"] = "command_sent_but_state_mismatch"
        log("No se confirmó por mismatch lógico; no se redescubre IP.", rid)

    return result


# =========================================================
# PARSER DE COMANDOS
# =========================================================
def clean_text(text):
    return " ".join(str(text).lower().strip().split())


def extract_number_after_keywords(text, keywords):
    for kw in keywords:
        m = re.search(rf"{kw}\s+(\d{{1,3}})", text)
        if m:
            return int(m.group(1))
    return None


def parse_command(pregunta):
    p = clean_text(pregunta)

    # restore / undo primero
    if any(x in p for x in ["deshacer", "como estaba antes", "cómo estaba antes", "ultimo estado anterior", "último estado anterior"]):
        return {"intent": "restore_previous"}

    if any(x in p for x in ["restaurar", "restaura", "como estaba", "cómo estaba", "ultimo estado", "último estado"]):
        return {"intent": "restore_current"}

    # escenas
    if "lectura" in p:
        return {"intent": "scene", "scene": "lectura"}

    if "relax" in p:
        return {"intent": "scene", "scene": "relax"}

    if "noche" in p:
        return {"intent": "scene", "scene": "noche"}

    if "normal" in p:
        return {"intent": "scene", "scene": "normal"}

    # on/off
    if any(x in p for x in ["apagar luz", "apaga luz", "apagar lampara", "apagar lámpara", "apaga lampara", "apaga lámpara", "luz off", "lampara off", "lámpara off"]):
        return {"intent": "switch", "value": False}

    if any(x in p for x in ["encender luz", "prender luz", "enciende luz", "encender lampara", "encender lámpara", "prender lampara", "prender lámpara", "luz on", "lampara on", "lámpara on"]):
        return {"intent": "switch", "value": True}

    # presets temperatura
    if any(x in p for x in ["calido", "cálido", "luz cálida", "luz calida", "modo cálido", "modo calido"]):
        return {"intent": "temp_preset", "preset": "calido"}

    if any(x in p for x in ["frio", "frío", "luz fría", "luz fria", "modo frío", "modo frio"]):
        return {"intent": "temp_preset", "preset": "frio"}

    # brillo %
    bright = extract_number_after_keywords(p, ["brillo", "intensidad"])
    if bright is not None:
        return {"intent": "brightness_percent", "value": clamp(bright, 0, 100)}

    # temperatura %
    temp = extract_number_after_keywords(p, ["temperatura", "temp"])
    if temp is not None:
        return {"intent": "temp_percent", "value": clamp(temp, 0, 100)}

    # fallback por palabra dispositivo
    if any(x in p for x in ["luz", "lampara", "lámpara", "cuarto"]):
        return {"intent": "status_or_default"}

    return {"intent": "unknown"}


def can_handle(pregunta):
    parsed = parse_command(pregunta)
    return parsed["intent"] != "unknown"


# =========================================================
# ACCIONES UX
# =========================================================
def scene_to_state(scene_name, current_state=None):
    base = current_state or get_cached_current_state() or {}

    if scene_name == "lectura":
        return snapshot_from_scene(SCENE_LECTURA, base)

    if scene_name == "relax":
        return snapshot_from_scene(SCENE_RELAX, base)

    if scene_name == "noche":
        return snapshot_from_scene(SCENE_NOCHE, base)

    if scene_name == "normal":
        return snapshot_from_scene(SCENE_NORMAL, base)

    raise ValueError(f"Escena desconocida: {scene_name}")


def apply_scene(scene_name, rid=None):
    predicted = scene_to_state(scene_name)
    expected = build_expected_from_state_block(predicted)

    def _action(device):
        if scene_name == "lectura":
            run_scene(device, SCENE_LECTURA, rid)
        elif scene_name == "relax":
            run_scene(device, SCENE_RELAX, rid)
        elif scene_name == "noche":
            run_scene(device, SCENE_NOCHE, rid)
        elif scene_name == "normal":
            run_scene(device, SCENE_NORMAL, rid)
        else:
            raise ValueError(f"Escena inválida: {scene_name}")

    result = execute_with_confirmation(
        _action,
        expected=expected,
        predicted_state=predicted,
        rid=rid
    )

    labels = {
        "lectura": "Escena lectura aplicada",
        "relax": "Escena relax aplicada",
        "noche": "Escena noche aplicada",
        "normal": "Modo normal aplicado",
    }

    return format_response(labels[scene_name], f"No se pudo aplicar {scene_name}", result)


def apply_switch(turn_on, rid=None):
    current = get_cached_current_state() or {}
    predicted = dict(current)
    predicted["switch"] = bool(turn_on)
    predicted["updated_at"] = int(time.time())

    expected = {"switch": bool(turn_on)}

    def _action(device):
        if turn_on:
            device.turn_on()
        else:
            device.turn_off()

    result = execute_with_confirmation(
        _action,
        expected=expected,
        predicted_state=predicted,
        rid=rid
    )

    return format_response(
        "Luz encendida" if turn_on else "Luz apagada",
        "No se pudo encender la luz" if turn_on else "No se pudo apagar la luz",
        result
    )


def apply_brightness_percent(percent, rid=None):
    value = percent_to_brightness(percent)
    current = get_cached_current_state() or {"switch": True, "mode": "white", "temp": 650}
    predicted = dict(current)

    predicted["switch"] = True
    predicted["mode"] = "white"
    predicted["brightness"] = value
    if predicted.get("temp") is None:
        predicted["temp"] = 650
    predicted["updated_at"] = int(time.time())

    expected = {
        "switch": True,
        "mode": "white",
        "brightness": value,
        "temp": int(predicted["temp"])
    }

    def _action(device):
        device.set_mode("white")
        time.sleep(0.20)
        device.turn_on()
        time.sleep(0.20)
        device.set_brightness(value)

    result = execute_with_confirmation(
        _action,
        expected=expected,
        predicted_state=predicted,
        rid=rid
    )

    return format_response(
        f"Brillo ajustado a {percent}%",
        f"No se pudo ajustar el brillo a {percent}%",
        result
    )


def apply_temp_percent(percent, rid=None):
    value = percent_to_temp(percent)
    current = get_cached_current_state() or {"switch": True, "mode": "white", "brightness": 800}
    predicted = dict(current)

    predicted["switch"] = True
    predicted["mode"] = "white"
    predicted["temp"] = value
    if predicted.get("brightness") is None:
        predicted["brightness"] = 800
    predicted["updated_at"] = int(time.time())

    expected = {
        "switch": True,
        "mode": "white",
        "brightness": int(predicted["brightness"]),
        "temp": value
    }

    def _action(device):
        device.set_mode("white")
        time.sleep(0.20)
        device.turn_on()
        time.sleep(0.20)
        if predicted.get("brightness") is not None:
            device.set_brightness(int(predicted["brightness"]))
            time.sleep(0.20)
        device.set_colourtemp(value)

    result = execute_with_confirmation(
        _action,
        expected=expected,
        predicted_state=predicted,
        rid=rid
    )

    return format_response(
        f"Temperatura ajustada a {percent}%",
        f"No se pudo ajustar la temperatura a {percent}%",
        result
    )


def apply_temp_preset(preset_name, rid=None):
    current = get_cached_current_state() or {"switch": True, "mode": "white", "brightness": 800}

    if preset_name == "calido":
        predicted = dict(current)
        predicted.update(PRESET_CALIDO)
        if predicted.get("brightness") is None:
            predicted["brightness"] = 800

    elif preset_name == "frio":
        predicted = dict(current)
        predicted.update(PRESET_FRIO)
        if predicted.get("brightness") is None:
            predicted["brightness"] = 800

    else:
        raise ValueError("Preset inválido")

    predicted["updated_at"] = int(time.time())
    expected = build_expected_from_state_block(predicted)

    def _action(device):
        device.set_mode("white")
        time.sleep(0.20)
        device.turn_on()
        time.sleep(0.20)
        if predicted.get("brightness") is not None:
            device.set_brightness(int(predicted["brightness"]))
            time.sleep(0.20)
        device.set_colourtemp(int(predicted["temp"]))

    result = execute_with_confirmation(
        _action,
        expected=expected,
        predicted_state=predicted,
        rid=rid
    )

    label = "Modo cálido aplicado" if preset_name == "calido" else "Modo frío aplicado"
    fail = "No se pudo aplicar modo cálido" if preset_name == "calido" else "No se pudo aplicar modo frío"

    return format_response(label, fail, result)


def restore_from_cache(use_previous=False, rid=None):
    target = get_cached_previous_state() if use_previous else get_cached_current_state()

    if not target:
        return {
            "respuesta": "No hay estado guardado para restaurar.",
            "cerebro": "SteckLight",
            "debug": {"ok": False, "reason": "no_cached_state"}
        }

    expected = build_expected_from_state_block(target, include_color=False)

    def _action(device):
        apply_snapshot(device, target, rid)

    result = execute_with_confirmation(
        _action,
        expected=expected,
        predicted_state=target,
        rid=rid
    )

    success_msg = "Estado anterior restaurado" if use_previous else "Estado restaurado"
    fail_msg = "No se pudo restaurar el estado anterior" if use_previous else "No se pudo restaurar el estado"

    return format_response(success_msg, fail_msg, result)


def get_status_response(rid=None):
    try:
        device, ip, st = get_working_device(force_discovery=False, rid=rid)
        state = normalize_state_from_status(st)

        return {
            "respuesta": f"Estado actual leído correctamente (IP {ip})",
            "cerebro": "SteckLight",
            "debug": {
                "ok": True,
                "ip": ip,
                "state": state,
                "raw_status": st
            }
        }
    except Exception as e:
        return {
            "respuesta": f"No se pudo leer el estado de la lámpara: {e}",
            "cerebro": "SteckLight",
            "debug": {"ok": False, "error": str(e)}
        }


# =========================================================
# ENTRYPOINTS DEL PLUGIN
# =========================================================
def responder(pregunta):
    rid = str(int(time.time() * 1000))[-6:]
    parsed = parse_command(pregunta)

    with DEVICE_LOCK:
        try:
            intent = parsed["intent"]

            if intent == "scene":
                return apply_scene(parsed["scene"], rid=rid)

            if intent == "switch":
                return apply_switch(parsed["value"], rid=rid)

            if intent == "brightness_percent":
                return apply_brightness_percent(parsed["value"], rid=rid)

            if intent == "temp_percent":
                return apply_temp_percent(parsed["value"], rid=rid)

            if intent == "temp_preset":
                return apply_temp_preset(parsed["preset"], rid=rid)

            if intent == "restore_previous":
                return restore_from_cache(use_previous=True, rid=rid)

            if intent == "restore_current":
                return restore_from_cache(use_previous=False, rid=rid)

            if intent == "status_or_default":
                return get_status_response(rid=rid)

            return {
                "respuesta": "No entendí el comando de luz.",
                "cerebro": "SteckLight",
                "debug": {"ok": False, "parsed": parsed}
            }

        except Exception as e:
            return {
                "respuesta": f"Error interno controlando la lámpara: {e}",
                "cerebro": "SteckLight",
                "debug": {"ok": False, "error": repr(e), "parsed": parsed}
            }


# aliases por compatibilidad con distintos cores
def run(pregunta):
    return responder(pregunta)

def handle(pregunta):
    return responder(pregunta)

def execute(pregunta):
    return responder(pregunta)
