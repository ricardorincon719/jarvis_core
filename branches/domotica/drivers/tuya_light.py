import json
import time
import threading
from pathlib import Path

import tinytuya

VERSION = "3.1.1"
DESCRIPTION = "Driver robusto y rápido para lámpara Tuya local con cache de IP, confirmación corta y restore/undo"
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


class TuyaLightDriver:
    def __init__(self, device_config: dict):
        self.name = device_config["name"]
        self.device_id = device_config["device_id"]
        self.local_key = device_config["local_key"]
        self.default_ip = device_config["ip"]
        self.version = float(device_config.get("version", 3.3))
        self.mac = str(device_config.get("mac", "")).lower()

        self.cache_file = Path(__file__).resolve().parent / f"{self.name}_cache.json"
        self.device_lock = threading.Lock()

        # DPS Tuya / Steck
        self.DPS_SWITCH = "20"
        self.DPS_MODE = "21"
        self.DPS_BRIGHT = "22"
        self.DPS_TEMP = "23"
        self.DPS_COLOR = "24"

        # Transporte / UX
        self.SOCKET_TIMEOUT = int(device_config.get("socket_timeout", 3))
        self.SOCKET_RETRY_LIMIT = int(device_config.get("socket_retry_limit", 1))
        self.CONFIRM_RETRIES = int(device_config.get("confirm_retries", 1))
        self.CONFIRM_DELAY = float(device_config.get("confirm_delay", 0.35))
        self.DISCOVERY_TIMEOUT = int(device_config.get("discovery_timeout", 4))

        # Delays internos entre subcomandos
        self.STEP_DELAY = float(device_config.get("step_delay", 0.10))
        self.MODE_DELAY = float(device_config.get("mode_delay", self.STEP_DELAY))
        self.SWITCH_DELAY = float(device_config.get("switch_delay", self.STEP_DELAY))
        self.BRIGHT_DELAY = float(device_config.get("bright_delay", self.STEP_DELAY))
        self.TEMP_DELAY = float(device_config.get("temp_delay", self.STEP_DELAY))
        self.COLOR_DELAY = float(device_config.get("color_delay", self.STEP_DELAY))

        # Rangos
        self.BRIGHT_MIN = int(device_config.get("bright_min", 10))
        self.BRIGHT_MAX = int(device_config.get("bright_max", 1000))
        self.TEMP_MIN = int(device_config.get("temp_min", 0))
        self.TEMP_MAX = int(device_config.get("temp_max", 1000))

    # =========================================================
    # LOG
    # =========================================================
    def _log(self, msg, rid=None):
        prefix = f"[TuyaLightDriver][{self.name}][{rid}]" if rid else f"[TuyaLightDriver][{self.name}]"
        print(f"{prefix} {msg}")

    # =========================================================
    # CACHE
    # =========================================================
    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception as e:
                self._log(f"Error leyendo cache: {e}")
        return {}

    def _save_cache(self, data):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log(f"Error guardando cache: {e}")

    def _get_cached_ip(self):
        cache = self._load_cache()
        return cache.get("ip", self.default_ip)

    def _normalize_state_from_status(self, status_data):
        if not isinstance(status_data, dict):
            return None

        dps = status_data.get("dps", {})
        if not isinstance(dps, dict):
            return None

        mode = dps.get(self.DPS_MODE)

        state = {
            "switch": bool(dps.get(self.DPS_SWITCH)) if dps.get(self.DPS_SWITCH) is not None else None,
            "mode": mode,
            "brightness": dps.get(self.DPS_BRIGHT),
            "temp": dps.get(self.DPS_TEMP),
            "updated_at": int(time.time()),
        }

        if mode == "colour":
            state["color"] = dps.get(self.DPS_COLOR)
            state["raw_colour"] = dps.get(self.DPS_COLOR)
        else:
            state["color"] = None
            state["raw_colour"] = None

        return state

    def _compare_states(self, a, b):
        if not a or not b:
            return False
        aa = {k: v for k, v in a.items() if k != "updated_at"}
        bb = {k: v for k, v in b.items() if k != "updated_at"}
        return aa == bb

    def _push_previous_state_if_needed(self, cache, new_state):
        current_state = cache.get("current_state")
        if current_state and new_state and not self._compare_states(current_state, new_state):
            cache["previous_state"] = current_state

    def _update_cache_with_state(self, ip, status_data=None, state_override=None):
        cache = self._load_cache()
        cache["ip"] = ip
        cache["updated_at"] = int(time.time())
        cache["mac"] = self.mac

        new_state = state_override or self._normalize_state_from_status(status_data)
        if new_state:
            self._push_previous_state_if_needed(cache, new_state)
            cache["current_state"] = new_state

            # compatibilidad / fallback
            cache["last_switch"] = new_state.get("switch")
            cache["last_mode"] = new_state.get("mode")
            cache["last_brightness"] = new_state.get("brightness")
            cache["last_temp"] = new_state.get("temp")
            cache["last_color"] = new_state.get("color")
            cache["last_raw_colour"] = new_state.get("raw_colour")

        self._save_cache(cache)

    def _get_cached_current_state(self):
        cache = self._load_cache()
        state = cache.get("current_state")
        if state:
            return state

        fallback = {
            "switch": cache.get("last_switch"),
            "mode": cache.get("last_mode"),
            "brightness": cache.get("last_brightness"),
            "temp": cache.get("last_temp"),
            "color": cache.get("last_color"),
            "raw_colour": cache.get("last_raw_colour"),
            "updated_at": int(time.time()),
        }

        if any(v is not None for v in fallback.values()):
            return fallback
        return None

    def _get_cached_previous_state(self):
        cache = self._load_cache()
        return cache.get("previous_state")

    # =========================================================
    # DEVICE / STATUS
    # =========================================================
    def _build_device(self, ip: str):
        d = tinytuya.BulbDevice(self.device_id, ip, self.local_key)
        d.set_version(self.version)
        d.set_socketPersistent(False)
        d.set_socketNODELAY(True)
        d.set_socketRetryLimit(self.SOCKET_RETRY_LIMIT)
        d.set_socketTimeout(self.SOCKET_TIMEOUT)
        return d

    def _safe_status(self, dev, rid=None):
        try:
            st = dev.status()
            self._log(f"status() => {st}", rid)
            return st
        except Exception as e:
            self._log(f"status() falló: {type(e).__name__}: {repr(e)}", rid)
            return None

    def _is_valid_status(self, st):
        if not isinstance(st, dict):
            return False
        if st.get("Err") is not None:
            return False
        if not isinstance(st.get("dps"), dict):
            return False
        return True

    def _get_dps(self, status_data):
        if not isinstance(status_data, dict):
            return {}
        dps = status_data.get("dps", {})
        return dps if isinstance(dps, dict) else {}

    def _extract(self, status_data, dps_key):
        return self._get_dps(status_data).get(dps_key)

    def _discover_ip(self, rid=None):
        self._log("Intentando redescubrir IP...", rid)
        try:
            scanned = tinytuya.deviceScan(False, self.DISCOVERY_TIMEOUT)
            self._log(f"deviceScan() => {scanned}", rid)

            if isinstance(scanned, dict):
                for ip, info in scanned.items():
                    if not isinstance(info, dict):
                        continue

                    gwid = info.get("gwId") or info.get("id")
                    scanned_mac = str(info.get("mac", "")).lower()

                    if gwid == self.device_id or (self.mac and scanned_mac == self.mac):
                        self._log(f"IP redescubierta: {ip}", rid)
                        return ip
        except Exception as e:
            self._log(f"deviceScan() falló: {e}", rid)

        self._log("No se redescubrió IP, usando fallback", rid)
        return self._get_cached_ip()

    def _get_working(self, force_discovery=False, rid=None):
        candidates = []

        if force_discovery:
            discovered_ip = self._discover_ip(rid)
            if discovered_ip:
                candidates.append(discovered_ip)

        cached_ip = self._get_cached_ip()
        if cached_ip not in candidates:
            candidates.append(cached_ip)

        if self.default_ip not in candidates:
            candidates.append(self.default_ip)

        last_error = None
        seen = set()

        for ip in candidates:
            if not ip or ip in seen:
                continue
            seen.add(ip)

            self._log(f"Probando IP: {ip}", rid)

            try:
                dev = self._build_device(ip)
                st = self._safe_status(dev, rid)

                if self._is_valid_status(st):
                    self._update_cache_with_state(ip, st)
                    self._log(f"IP válida: {ip}", rid)
                    return dev, ip, st

                if isinstance(st, dict) and st.get("Err") is not None:
                    last_error = f"tuya_err_{st.get('Err')}"
                else:
                    last_error = "status_invalid"

                self._log(f"IP descartada {ip}: {st}", rid)

            except Exception as e:
                last_error = str(e)
                self._log(f"Error probando IP {ip}: {e}", rid)

        if not force_discovery:
            self._log(f"Sin IP válida en cache/default ({last_error}); forzando discovery...", rid)
            discovered_ip = self._discover_ip(rid)
            if discovered_ip and discovered_ip not in seen:
                self._log(f"Probando IP descubierta: {discovered_ip}", rid)
                try:
                    dev = self._build_device(discovered_ip)
                    st = self._safe_status(dev, rid)

                    if self._is_valid_status(st):
                        self._update_cache_with_state(discovered_ip, st)
                        self._log(f"IP válida tras discovery: {discovered_ip}", rid)
                        return dev, discovered_ip, st

                    if isinstance(st, dict) and st.get("Err") is not None:
                        last_error = f"tuya_err_{st.get('Err')}"
                    else:
                        last_error = "status_invalid"

                    self._log(f"IP descubierta descartada {discovered_ip}: {st}", rid)

                except Exception as e:
                    last_error = str(e)
                    self._log(f"Error probando IP descubierta {discovered_ip}: {e}", rid)

        raise RuntimeError(f"No se pudo conectar a {self.name}. Último error: {last_error}")

    # =========================================================
    # HELPERS
    # =========================================================
    def clamp(self, value, min_value, max_value):
        return max(min_value, min(max_value, int(value)))

    def percent_to_brightness(self, percent):
        percent = self.clamp(percent, 0, 100)
        if percent == 0:
            return self.BRIGHT_MIN
        return int(self.BRIGHT_MIN + ((self.BRIGHT_MAX - self.BRIGHT_MIN) * (percent / 100.0)))

    def percent_to_temp(self, percent):
        percent = self.clamp(percent, 0, 100)
        return int(self.TEMP_MIN + ((self.TEMP_MAX - self.TEMP_MIN) * (percent / 100.0)))

    def _snapshot_from_scene(self, scene, base_state=None):
        state = dict(base_state or {})
        state.update(scene)
        state["updated_at"] = int(time.time())
        return state

    def _build_expected_from_state_block(self, state_block, include_color=True):
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

        if include_color and state_block.get("mode") == "colour":
            if state_block.get("raw_colour") is not None:
                expected["color"] = str(state_block.get("raw_colour"))
            elif state_block.get("color") is not None:
                expected["color"] = str(state_block.get("color"))

        return expected

    def _matches_expected(self, status_data, expected):
        if not expected:
            return True

        ok = True

        if "switch" in expected:
            switch_value = self._extract(status_data, self.DPS_SWITCH)
            ok = ok and (bool(switch_value) is expected["switch"])

        if "mode" in expected:
            mode_value = self._extract(status_data, self.DPS_MODE)
            ok = ok and (mode_value == expected["mode"])

        if "brightness" in expected:
            bright_value = self._extract(status_data, self.DPS_BRIGHT)
            ok = ok and (bright_value is not None) and (int(bright_value) == int(expected["brightness"]))

        if "temp" in expected:
            temp_value = self._extract(status_data, self.DPS_TEMP)
            ok = ok and (temp_value is not None) and (int(temp_value) == int(expected["temp"]))

        if "color" in expected:
            color_value = self._extract(status_data, self.DPS_COLOR)
            ok = ok and (str(color_value).lower() == str(expected["color"]).lower())

        return ok

    def _confirm_expected(self, dev, expected=None, retries=None, delay=None, rid=None):
        if retries is None:
            retries = self.CONFIRM_RETRIES
        if delay is None:
            delay = self.CONFIRM_DELAY

        last_status = None

        for i in range(retries):
            time.sleep(delay)
            st = self._safe_status(dev, rid)
            last_status = st

            if st is None or not self._is_valid_status(st):
                self._log(f"Confirmación {i + 1}/{retries}: transport_error", rid)
                continue

            matched = self._matches_expected(st, expected)
            self._log(f"Confirmación {i + 1}/{retries}: matched={matched}", rid)

            if matched:
                return True, st, "matched"

        if last_status is None or not self._is_valid_status(last_status):
            return False, None, "transport_error"

        return False, last_status, "mismatch"

    def _classify_result(self, result):
        if result["ok"]:
            return "confirmed"
        if result["sent"] and result["failure_reason"] == "mismatch":
            return "sent_but_unconfirmed"
        if result["sent"] and result["failure_reason"] == "transport_error":
            return "transport_error"
        return "failed"

    # =========================================================
    # APLICACIÓN DE ESTADOS
    # =========================================================
    def _run_scene(self, dev, scene, rid=None):
        mode = scene.get("mode")
        switch = scene.get("switch")
        brightness = scene.get("brightness")
        temp = scene.get("temp")

        # Soportar ambos formatos:
        # - scene["color"] = "red"/"green"/"blue"
        # - scene["rgb"] = [255, 0, 0]
        color = scene.get("color")
        rgb = scene.get("rgb")
        raw_colour = scene.get("raw_colour")

        if mode:
            self._log(f"Aplicando modo: {mode}", rid)
            dev.set_mode(mode)
            time.sleep(self.MODE_DELAY)

        if switch is not None:
            if switch:
                self._log("Aplicando switch ON", rid)
                dev.turn_on()
            else:
                self._log("Aplicando switch OFF", rid)
                dev.turn_off()
            time.sleep(self.SWITCH_DELAY)

        if mode == "white":
            if brightness is not None:
                self._log(f"Aplicando brightness: {brightness}", rid)
                dev.set_brightness(int(brightness))
                time.sleep(self.BRIGHT_DELAY)

            if temp is not None:
                self._log(f"Aplicando temp: {temp}", rid)
                dev.set_colourtemp(int(temp))
                time.sleep(self.TEMP_DELAY)

        elif mode == "colour":
            rgb_map = {
                "red": (255, 0, 0),
                "green": (0, 255, 0),
                "blue": (0, 0, 255),
            }

            if isinstance(color, str) and color.lower() in rgb_map:
                r, g, b = rgb_map[color.lower()]
                self._log(f"Aplicando color RGB desde nombre: {r},{g},{b}", rid)
                dev.set_colour(r, g, b)
                time.sleep(self.COLOR_DELAY)

            elif isinstance(rgb, (list, tuple)) and len(rgb) == 3:
                r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
                self._log(f"Aplicando color RGB directo: {r},{g},{b}", rid)
                dev.set_colour(r, g, b)
                time.sleep(self.COLOR_DELAY)

            elif raw_colour:
                self._log(f"Aplicando raw_colour DPS: {raw_colour}", rid)
                dev.set_value(int(self.DPS_COLOR), raw_colour)
                time.sleep(self.COLOR_DELAY)

            else:
                self._log("Modo colour sin color/rgb/raw_colour válido", rid)

            if brightness is not None:
                self._log(f"Aplicando brightness en colour: {brightness}", rid)
                dev.set_brightness(int(brightness))
                time.sleep(self.BRIGHT_DELAY)

    def _apply_snapshot(self, dev, snapshot, rid=None):
        if not snapshot:
            return
        self._run_scene(dev, snapshot, rid=rid)

    # =========================================================
    # MOTOR
    # =========================================================
    def _execute_with_confirmation(self, action_fn, expected=None, predicted_state=None, rid=None):
        try:
            dev, ip, before = self._get_working(force_discovery=False, rid=rid)
        except Exception as e:
            self._log(f"Primer intento falló: {e}", rid)
            dev, ip, before = self._get_working(force_discovery=True, rid=rid)

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
            if self._is_valid_status(before):
                self._update_cache_with_state(ip, before)

            action_fn(dev)
            result["sent"] = True

        except Exception as e:
            result["error"] = f"send_failed: {e}"
            result["failure_reason"] = "transport_error"
            result["classification"] = self._classify_result(result)
            try:
                self._log("Fallo al enviar; redescubriendo IP y reintentando...", rid)
                dev, ip, before = self._get_working(force_discovery=True, rid=rid)
                result["ip"] = ip
                result["state_before"] = before

                action_fn(dev)
                result["sent"] = True

                confirmed, after, reason = self._confirm_expected(
                    dev,
                    expected=expected,
                    retries=self.CONFIRM_RETRIES,
                    delay=self.CONFIRM_DELAY,
                    rid=rid,
                )

                result["state_after"] = after
                result["confirmed"] = confirmed
                result["ok"] = confirmed
                result["failure_reason"] = None if confirmed else reason
                result["classification"] = self._classify_result(result)

                if after is not None:
                    self._update_cache_with_state(ip, after)
                elif predicted_state is not None and result["sent"]:
                    self._update_cache_with_state(ip, state_override=predicted_state)

            except Exception as retry_error:
                result["error"] = f"send_retry_failed: {retry_error}"
                result["classification"] = self._classify_result(result)
            return result

        confirmed, after, reason = self._confirm_expected(
            dev,
            expected=expected,
            retries=self.CONFIRM_RETRIES,
            delay=self.CONFIRM_DELAY,
            rid=rid,
        )

        result["state_after"] = after
        result["confirmed"] = confirmed
        result["ok"] = confirmed
        result["failure_reason"] = None if confirmed else reason
        result["classification"] = self._classify_result(result)

        if after is not None:
            self._update_cache_with_state(ip, after)
        elif predicted_state is not None and result["sent"]:
            self._update_cache_with_state(ip, state_override=predicted_state)

        # fallback solo si hubo error de transporte tras enviar
        if result["sent"] and not result["confirmed"] and reason == "transport_error":
            result["error"] = "transport_error_after_send"

            try:
                self._log("Fallo de transporte tras envío; redescubriendo IP...", rid)
                dev, ip, _ = self._get_working(force_discovery=True, rid=rid)
                result["ip"] = ip

                self._log("Reenviando comando tras redescubrimiento...", rid)
                action_fn(dev)

                confirmed, after, reason = self._confirm_expected(
                    dev,
                    expected=expected,
                    retries=self.CONFIRM_RETRIES,
                    delay=self.CONFIRM_DELAY,
                    rid=rid,
                )

                result["state_after"] = after
                result["confirmed"] = confirmed
                result["ok"] = confirmed
                result["failure_reason"] = None if confirmed else reason
                result["classification"] = self._classify_result(result)

                if after is not None:
                    self._update_cache_with_state(ip, after)
                elif predicted_state is not None:
                    self._update_cache_with_state(ip, state_override=predicted_state)

            except Exception as e:
                result["error"] = f"rediscovery_retry_failed: {e}"
                result["classification"] = self._classify_result(result)

        return result

    # =========================================================
    # API PÚBLICA
    # =========================================================
    def get_status(self, rid=None):
        with self.device_lock:
            _, ip, st = self._get_working(force_discovery=False, rid=rid)
            return {"ok": True, "ip": ip, "status": st}

    def turn_on(self, rid=None):
        with self.device_lock:
            base = self._get_cached_current_state() or {}
            predicted = dict(base)
            predicted["switch"] = True
            predicted["updated_at"] = int(time.time())

            return self._execute_with_confirmation(
                lambda d: d.turn_on(),
                expected={"switch": True},
                predicted_state=predicted,
                rid=rid,
            )

    def turn_off(self, rid=None):
        with self.device_lock:
            base = self._get_cached_current_state() or {}
            predicted = dict(base)
            predicted["switch"] = False
            predicted["updated_at"] = int(time.time())

            return self._execute_with_confirmation(
                lambda d: d.turn_off(),
                expected={"switch": False},
                predicted_state=predicted,
                rid=rid,
            )

    def apply_scene(self, scene: dict, rid=None):
        with self.device_lock:
            base_state = self._get_cached_current_state() or {}
            predicted = self._snapshot_from_scene(scene, base_state=base_state)
            expected = self._build_expected_from_state_block(predicted)

            result = self._execute_with_confirmation(
                lambda d: self._run_scene(d, scene, rid=rid),
                expected=expected,
                predicted_state=predicted,
                rid=rid,
            )
            result["scene"] = scene
            return result

    def set_white(self, brightness=None, temp=None, switch=True, rid=None):
        scene = {
            "switch": switch,
            "mode": "white",
        }
        if brightness is not None:
            scene["brightness"] = int(brightness)
        if temp is not None:
            scene["temp"] = int(temp)
        return self.apply_scene(scene, rid=rid)

    def set_brightness_percent(self, percent, rid=None):
        brightness = self.percent_to_brightness(percent)
        base = self._get_cached_current_state() or {}
        temp = base.get("temp", 650)
        return self.apply_scene(
            {
                "switch": True,
                "mode": "white",
                "brightness": brightness,
                "temp": temp,
            },
            rid=rid,
        )

    def set_temp_percent(self, percent, rid=None):
        temp = self.percent_to_temp(percent)
        base = self._get_cached_current_state() or {}
        brightness = base.get("brightness", 800)
        return self.apply_scene(
            {
                "switch": True,
                "mode": "white",
                "brightness": brightness,
                "temp": temp,
            },
            rid=rid,
        )

    def restore_previous_state(self, rid=None):
        with self.device_lock:
            previous = self._get_cached_previous_state()
            if not previous:
                return {
                    "ok": False,
                    "error": "no_previous_state",
                    "classification": "failed",
                }

            expected = self._build_expected_from_state_block(previous)
            result = self._execute_with_confirmation(
                lambda d: self._apply_snapshot(d, previous, rid=rid),
                expected=expected,
                predicted_state=previous,
                rid=rid,
            )
            result["restored_state"] = previous
            return result

    def restore_current_state(self, rid=None):
        with self.device_lock:
            current = self._get_cached_current_state()
            if not current:
                return {
                    "ok": False,
                    "error": "no_current_state",
                    "classification": "failed",
                }

            expected = self._build_expected_from_state_block(current)
            result = self._execute_with_confirmation(
                lambda d: self._apply_snapshot(d, current, rid=rid),
                expected=expected,
                predicted_state=current,
                rid=rid,
            )
            result["restored_state"] = current
            return result
