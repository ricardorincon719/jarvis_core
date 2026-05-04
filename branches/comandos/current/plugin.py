VERSION = "2.4.0"
DESCRIPTION = "Control robusto de lámpara Tuya local (Steck) con escenas domésticas, restauración y memoria de estado actual/anterior"

TRIGGERS = [
    "luz", "lampara", "lámpara", "cuarto",
    "lectura", "relax", "noche",
    "restaura", "restaurar", "deshacer",
    "como estaba", "cómo estaba",
    "como estaba antes", "cómo estaba antes",
    "ultimo estado", "último estado"
]

import json
import time
import uuid
import threading
from pathlib import Path

import tinytuya

DEVICE_ID = "3483408310521cf4c753"
LOCAL_KEY = "k~)0B|~.=~[(U!p@"
DEFAULT_IP = "192.168.100.107"
MAC = "10:52:1c:f4:c7:53"
TUYA_VERSION = 3.3

CACHE_FILE = Path(__file__).resolve().parent / "device_cache.json"

DEVICE_LOCK = threading.Lock()

DPS_SWITCH = "20"
DPS_MODE = "21"
DPS_BRIGHT = "22"
DPS_TEMP = "23"
DPS_COLOR = "24"

# Escenas domésticas
SCENE_NORMAL = {"switch": True, "mode": "white", "brightness": 800, "temp": 650}
SCENE_LECTURA = {"switch": True, "mode": "white", "brightness": 1000, "temp": 850}
SCENE_RELAX = {"switch": True, "mode": "white", "brightness": 350, "temp": 150}
SCENE_NOCHE = {"switch": True, "mode": "white", "brightness": 80, "temp": 60}


def log(msg, rid=None):
    prefix = f"[SteckLight][{rid}]" if rid else "[SteckLight]"
    print(f"{prefix} {msg}")


def load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
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
        "switch": dps.get(DPS_SWITCH),
        "mode": dps.get(DPS_MODE),
        "brightness": dps.get(DPS_BRIGHT),
        "temp": dps.get(DPS_TEMP),
        "color": dps.get(DPS_COLOR),
        "updated_at": int(time.time())
    }


def update_cache_with_state(ip, status_data=None):
    cache = load_cache()
    cache["ip"] = ip
    cache["updated_at"] = int(time.time())
    cache["mac"] = MAC.lower()
    new_state = normalize_state_from_status(status_data)

    if new_state:
        current_state = cache.get("current_state")

        # Solo mover current -> previous si cambió de verdad el estado útil
        if current_state:
            current_compare = {k: v for k, v in current_state.items() if k != "updated_at"}
            new_compare = {k: v for k, v in new_state.items() if k != "updated_at"}

            if current_compare != new_compare:
                cache["previous_state"] = current_state

        cache["current_state"] = new_state

        # Compatibilidad con versiones previas
        cache["last_switch"] = new_state.get("switch")
        cache["last_mode"] = new_state.get("mode")
        cache["last_brightness"] = new_state.get("brightness")
        cache["last_temp"] = new_state.get("temp")
        cache["last_color"] = new_state.get("color")

    save_cache(cache)


def build_device(ip):
    d = tinytuya.BulbDevice(DEVICE_ID, ip, LOCAL_KEY,)
    d.set_version(TUYA_VERSION)
    d.set_socketPersistent(False)
    d.set_socketNODELAY(True)
    d.set_socketRetryLimit(2)
    d.set_socketTimeout(3)
    return d


def safe_status(device, rid=None):
    try:
        st = device.status()
        log(f"status() => {st}", rid)
        return st
    except Exception as e:
        log(f"status() falló: {type(e).__name__}: {repr(e)}", rid)
        return None


def get_dps(status_data):
    if not isinstance(status_data, dict):
        return {}
    dps = status_data.get("dps", {})
    return dps if isinstance(dps, dict) else {}


def extract_switch_state(status_data):
    dps = get_dps(status_data)
    value = dps.get(DPS_SWITCH)
    return None if value is None else bool(value)


def extract_mode(status_data):
    return get_dps(status_data).get(DPS_MODE)


def extract_temp(status_data):
    return get_dps(status_data).get(DPS_TEMP)


def extract_brightness(status_data):
    return get_dps(status_data).get(DPS_BRIGHT)


def extract_color(status_data):
    return get_dps(status_data).get(DPS_COLOR)


def discover_ip(rid=None):
    log("Intentando redescubrir IP local...", rid)
    try:
        scanned = tinytuya.deviceScan(False, 8)
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

def is_valid_status(status_data):
    if not isinstance(status_data, dict):
        return False

    # TinyTuya devuelve errores como dict con Err/Error
    if status_data.get("Err") is not None:
        return False

    dps = status_data.get("dps")
    if not isinstance(dps, dict):
        return False

    return True

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
            log(f"Probando dispositivo en IP: {ip}", rid)
            d = build_device(ip)
            st = safe_status(d, rid)

            if is_valid_status(st):
                update_cache_with_state(ip, st)
                log(f"Dispositivo válido en IP: {ip}", rid)
                return d, ip, st

            if isinstance(st, dict) and st.get("Err") is not None:
                last_error = f"tuya_err_{st.get('Err')}"
                log(f"IP descartada {ip}: status con error {st}", rid)
            else:
                last_error = "status_none"
                log(f"IP descartada {ip}: status inválido o vacío", rid)

        except Exception as e:
            last_error = e
            log(f"Error probando IP {ip}: {e}", rid)

    raise RuntimeError(f"No se pudo conectar a la lámpara. Último error: {last_error}")


def color_matches(actual, expected):
    if not actual or not expected:
        return False
    return str(actual).lower() == str(expected).lower()


def temp_matches(actual, expected, tolerance=0):
    if actual is None or expected is None:
        return False
    return abs(int(actual) - int(expected)) <= tolerance


def brightness_matches(actual, expected, tolerance=0):
    if actual is None or expected is None:
        return False
    return abs(int(actual) - int(expected)) <= tolerance


def expected_matches(status_data, expected):
    if not expected:
        return True

    switch_value = extract_switch_state(status_data)
    mode_value = extract_mode(status_data)
    temp_value = extract_temp(status_data)
    bright_value = extract_brightness(status_data)
    color_value = extract_color(status_data)

    ok = True

    if "switch" in expected:
        ok = ok and (switch_value is expected["switch"])

    if "mode" in expected:
        ok = ok and (mode_value == expected["mode"])

    if "temp" in expected:
        ok = ok and temp_matches(temp_value, expected["temp"], tolerance=0)

    if "brightness" in expected:
        ok = ok and brightness_matches(bright_value, expected["brightness"], tolerance=0)

    if "color" in expected:
        ok = ok and color_matches(color_value, expected["color"])

    return ok


def explain_expected(expected):
    if not expected:
        return "sin validación específica"

    parts = []
    if "switch" in expected:
        parts.append(f"switch={expected['switch']}")
    if "mode" in expected:
        parts.append(f"mode={expected['mode']}")
    if "temp" in expected:
        parts.append(f"temp={expected['temp']}")
    if "brightness" in expected:
        parts.append(f"brightness={expected['brightness']}")
    if "color" in expected:
        parts.append(f"color={expected['color']}")
    return ", ".join(parts)


def confirm_expected_state(device, expected=None, retries=3, delay=1.0, rid=None):
    last_status = None

    for i in range(retries):
        time.sleep(delay)
        st = safe_status(device, rid)
        last_status = st

        if st is None or not is_valid_status(st):
           log(f"Confirmación intento {i + 1}/{retries}: transport_error", rid)
           continue

        matched = expected_matches(st, expected)
        log(
            f"Confirmación intento {i + 1}/{retries}: "
            f"esperado=({explain_expected(expected)}) | matched={matched}",
            rid
        )

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


def execute_with_confirmation(action_fn, expected=None, pre_mode=None, rid=None):
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
        if pre_mode is not None:
            log(f"Seteando modo previo: {pre_mode}", rid)
            device.set_mode(pre_mode)
            time.sleep(0.4)

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
        retries=3,
        delay=1.0,
        rid=rid
    )

    result["state_after"] = after
    result["confirmed"] = confirmed
    result["ok"] = confirmed
    result["failure_reason"] = None if confirmed else reason
    result["classification"] = classify_result(result)

    if after is not None:
        update_cache_with_state(ip, after)

    if result["sent"] and not result["confirmed"] and reason == "transport_error":
        result["error"] = "transport_error_after_send"
        try:
            log("Fallo de transporte tras el envío. Reintentando con redescubrimiento de IP...", rid)
            device, ip, _ = get_working_device(force_discovery=True, rid=rid)
            result["ip"] = ip

            if pre_mode is not None:
                log(f"Reaplicando modo previo: {pre_mode}", rid)
                device.set_mode(pre_mode)
                time.sleep(0.4)

            log("Reenviando comando tras redescubrimiento...", rid)
            action_fn(device)

            confirmed, after, reason = confirm_expected_state(
                device,
                expected=expected,
                retries=3,
                delay=1.0,
                rid=rid
            )

            result["state_after"] = after
            result["confirmed"] = confirmed
            result["ok"] = confirmed
            result["failure_reason"] = None if confirmed else reason
            result["classification"] = classify_result(result)

            if after is not None:
                update_cache_with_state(ip, after)

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


def run_scene(device, scene, rid=None):
    target_mode = scene.get("mode")

    if target_mode:
        log(f"Aplicando modo: {target_mode}", rid)
        device.set_mode(target_mode)
        time.sleep(0.3)

    if "switch" in scene:
        if scene["switch"]:
            log("Aplicando switch ON", rid)
            device.turn_on()
        else:
            log("Aplicando switch OFF", rid)
            device.turn_off()
        time.sleep(0.3)

    if target_mode == "white":
        if "brightness" in scene:
            log(f"Aplicando brightness: {scene['brightness']}", rid)
            device.set_brightness(scene["brightness"])
            time.sleep(0.3)

        if "temp" in scene:
            log(f"Aplicando temp: {scene['temp']}", rid)
            device.set_colourtemp(scene["temp"])
            time.sleep(0.3)

    elif target_mode == "colour":
        if "color" in scene:
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
                time.sleep(0.3)

        if "brightness" in scene:
            log(f"Aplicando brightness en colour: {scene['brightness']}", rid)
            device.set_brightness(scene["brightness"])
            time.sleep(0.3)


def build_expected_from_state_block(state_block):
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

    if state_block.get("mode") == "colour" and state_block.get("color") is not None:
        expected["color"] = str(state_block.get("color"))

    return expected

def build_expected_for_restore(state_block):
    """
    Igual que build_expected_from_state_block pero SIN validar color estricto.
    """
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

    # 🚫 NO validamos color para restore

    return expected

def build_restore_expected_from_cache(use_previous=False):
    cache = load_cache()

    if use_previous:
        state_block = cache.get("previous_state")
    else:
        state_block = cache.get("current_state")

    if not state_block:
        fallback = {
            "switch": cache.get("last_switch"),
            "mode": cache.get("last_mode"),
            "brightness": cache.get("last_brightness"),
            "temp": cache.get("last_temp"),
            "color": cache.get("last_color"),
        }
        state_block = fallback

    return build_expected_for_restore(state_block)


def restore_state_action(device, state_block, rid=None):
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
        time.sleep(0.3)

    if target_switch is not None:
        if bool(target_switch):
            log("Restaurando switch ON", rid)
            device.turn_on()
        else:
            log("Restaurando switch OFF", rid)
            device.turn_off()
        time.sleep(0.3)

    if target_mode == "white":
        if target_brightness is not None:
            log(f"Restaurando brightness: {target_brightness}", rid)
            device.set_brightness(int(target_brightness))
            time.sleep(0.3)

        if target_temp is not None:
            log(f"Restaurando temp: {target_temp}", rid)
            device.set_colourtemp(int(target_temp))
            time.sleep(0.3)

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
                time.sleep(0.3)

        if target_brightness is not None:
            log(f"Restaurando brightness en colour: {target_brightness}", rid)
            device.set_brightness(int(target_brightness))
            time.sleep(0.3)


def can_handle(pregunta):
    p = pregunta.lower().strip()

    direct_matches = [
        "lectura",
        "relax",
        "noche",
        "restaura",
        "restaurar",
        "deshacer",
        "como estaba",
        "cómo estaba",
        "como estaba antes",
        "cómo estaba antes",
        "ultimo estado",
        "último estado",
    ]

    if any(term in p for term in direct_matches):
        return True

    device_terms = ["luz", "lampara", "lámpara", "cuarto"]
    if any(term in p for term in device_terms):
        return True

    return False


def format_response(success_msg, fail_msg, result):
    if result["classification"] == "confirmed":
        return {
            "respuesta": f"{success_msg} (confirmado, IP {result['ip']})",
            "cerebro": "SteckLight",
            "debug": result,
        }

    if result["classification"] == "sent_but_unconfirmed":
        return {
            "respuesta": f"{fail_msg}: comando enviado pero estado no confirmó exactamente lo esperado (IP {result['ip']})",
            "cerebro": "SteckLight",
            "debug": result,
        }

    if result["classification"] == "transport_error":
        return {
            "respuesta": f"Error de transporte/control local de la lámpara (IP {result['ip']}): {result['error']}",
            "cerebro": "SteckLight",
            "debug": result,
        }

    return {
        "respuesta": f"Error controlando la lámpara: {result['error']}",
        "cerebro": "SteckLight",
        "debug": result,
    }


def handle(pregunta):
    with DEVICE_LOCK:
        return _handle_locked(pregunta)


def _handle_locked(pregunta):
    rid = str(uuid.uuid4())[:8]
    p = pregunta.lower().strip()
    log(f"Orden recibida: {p}", rid)

    try:
        # DESHACER / RESTAURAR ESTADO ANTERIOR
        if "restaura" in p or "restaurar" in p or "deshacer" in p or "como estaba antes" in p or "cómo estaba antes" in p:
            cache = load_cache()
            previous_state = cache.get("previous_state")
            expected = build_restore_expected_from_cache(use_previous=True)

            if not previous_state or not expected:
                return {
                    "respuesta": "No tengo un estado anterior confirmado para restaurar todavía.",
                    "cerebro": "SteckLight"
                }

            result = execute_with_confirmation(
                action_fn=lambda d: restore_state_action(d, previous_state, rid=rid),
                expected=expected,
                rid=rid,
            )
            return format_response(
                "Estado anterior restaurado",
                "No se pudo restaurar exactamente el estado anterior",
                result
            )

        # VOLVER AL ÚLTIMO ESTADO ACTUAL GUARDADO
        if "último estado" in p or "ultimo estado" in p or "como estaba" in p or "cómo estaba" in p:
            cache = load_cache()
            current_state = cache.get("current_state")
            expected = build_restore_expected_from_cache(use_previous=False)

            if not current_state and not expected:
                return {
                    "respuesta": "No tengo un estado actual guardado para restaurar todavía.",
                    "cerebro": "SteckLight"
                }

            result = execute_with_confirmation(
                action_fn=lambda d: restore_state_action(d, current_state, rid=rid),
                expected=expected,
                rid=rid,
            )
            return format_response(
                "Último estado restaurado",
                "No se pudo restaurar exactamente el último estado",
                result
            )

        # ESCENAS DOMÉSTICAS
        if "lectura" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: run_scene(d, SCENE_LECTURA, rid=rid),
                expected=SCENE_LECTURA,
                rid=rid,
            )
            return format_response(
                "Luz de lectura activada",
                "No se pudo confirmar la luz de lectura",
                result
            )

        if "relax" in p or "relaj" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: run_scene(d, SCENE_RELAX, rid=rid),
                expected=SCENE_RELAX,
                rid=rid,
            )
            return format_response(
                "Luz relax activada",
                "No se pudo confirmar la luz relax",
                result
            )

        if "noche" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: run_scene(d, SCENE_NOCHE, rid=rid),
                expected=SCENE_NOCHE,
                rid=rid,
            )
            return format_response(
                "Luz noche activada",
                "No se pudo confirmar la luz noche",
                result
            )

        # ON por defecto = escena normal
        if "prende" in p or "encende" in p or "enciende" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: run_scene(d, SCENE_NORMAL, rid=rid),
                expected=SCENE_NORMAL,
                rid=rid,
            )
            return format_response(
                "Lámpara encendida en modo normal",
                "La lámpara no confirmó el modo normal",
                result
            )

        # OFF
        if "apaga" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: d.turn_off(),
                expected={"switch": False},
                rid=rid,
            )
            return format_response(
                "Lámpara apagada",
                "La lámpara no confirmó apagado",
                result
            )

        # BRILLO
        if "brillo" in p:
            if "max" in p:
                result = execute_with_confirmation(
                    action_fn=lambda d: d.set_brightness(1000),
                    expected={"brightness": 1000},
                    rid=rid,
                )
                return format_response(
                    "Brillo al máximo",
                    "No se pudo confirmar el brillo máximo",
                    result
                )

            if "min" in p:
                result = execute_with_confirmation(
                    action_fn=lambda d: d.set_brightness(100),
                    expected={"brightness": 100},
                    rid=rid,
                )
                return format_response(
                    "Brillo bajo",
                    "No se pudo confirmar el brillo bajo",
                    result
                )

        # TEMPERATURA
        if "calida" in p or "cálida" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: d.set_colourtemp(0),
                expected={"switch": True, "mode": "white", "temp": 0},
                pre_mode="white",
                rid=rid,
            )
            return format_response(
                "Luz cálida",
                "No se pudo confirmar luz cálida",
                result
            )

        if "fria" in p or "fría" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: d.set_colourtemp(1000),
                expected={"switch": True, "mode": "white", "temp": 1000},
                pre_mode="white",
                rid=rid,
            )
            return format_response(
                "Luz fría",
                "No se pudo confirmar luz fría",
                result
            )

        # COLOR
        if "rojo" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: d.set_colour(255, 0, 0),
                expected={"switch": True, "mode": "colour", "color": "000003e803e8"},
                pre_mode="colour",
                rid=rid,
            )
            return format_response(
                "Luz roja",
                "No se pudo confirmar luz roja",
                result
            )

        if "azul" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: d.set_colour(0, 0, 255),
                expected={"switch": True, "mode": "colour", "color": "00f003e803e8"},
                pre_mode="colour",
                rid=rid,
            )
            return format_response(
                "Luz azul",
                "No se pudo confirmar luz azul",
                result
            )

        if "verde" in p:
            result = execute_with_confirmation(
                action_fn=lambda d: d.set_colour(0, 255, 0),
                expected={"switch": True, "mode": "colour", "color": "007803e803e8"},
                pre_mode="colour",
                rid=rid,
            )
            return format_response(
                "Luz verde",
                "No se pudo confirmar luz verde",
                result
            )

        if "estado" in p or "status" in p:
            d, ip, st = get_working_device(force_discovery=True, rid=rid)
            sw = extract_switch_state(st)
            mode = extract_mode(st)
            bright = extract_brightness(st)
            temp = extract_temp(st)
            color = extract_color(st)

            estado_txt = "encendida" if sw else "apagada"
            return {
                "respuesta": (
                    f"Estado actual: {estado_txt}, modo={mode}, brillo={bright}, "
                    f"temperatura={temp}, color={color}, IP {ip}"
                ),
                "cerebro": "SteckLight",
                "debug": {"ip": ip, "status": st},
            }

        return {
            "respuesta": "Entendí que es para la lámpara pero no reconocí la acción",
            "cerebro": "SteckLight"
        }

    except Exception as e:
        log(f"Error general: {e}", rid)
        return {
            "respuesta": f"Error controlando la lámpara: {e}",
            "cerebro": "SteckLight"
        }
