import json
import threading
import time
from pathlib import Path

import tinytuya


class TuyaPlugDriver:
    def __init__(self, device_config: dict):
        self.name = device_config["name"]
        self.device_id = device_config["device_id"]
        self.local_key = device_config["local_key"]
        self.default_ip = device_config["ip"]
        self.version = float(device_config.get("version", 3.3))
        self.mac = str(device_config.get("mac", "")).lower()
        self.dps_switch = str(device_config.get("dps_switch", "1"))
        self.socket_timeout = int(device_config.get("socket_timeout", 3))
        self.socket_retry_limit = int(device_config.get("socket_retry_limit", 1))
        self.discovery_timeout = int(device_config.get("discovery_timeout", 4))
        self.confirm_delay = float(device_config.get("confirm_delay", 0.35))
        self.cache_file = Path(__file__).resolve().parent / f"{self.name}_cache.json"
        self.device_lock = threading.Lock()

    def _log(self, msg):
        print(f"[TuyaPlugDriver][{self.name}] {msg}")

    def _load_cache(self):
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            self._log(f"Error leyendo cache: {exc}")
            return {}

    def _save_cache(self, data):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self._log(f"Error guardando cache: {exc}")

    def _cached_ip(self):
        return self._load_cache().get("ip") or self.default_ip

    def _build_device(self, ip: str):
        dev = tinytuya.OutletDevice(self.device_id, ip, self.local_key)
        dev.set_version(self.version)
        dev.set_socketPersistent(False)
        dev.set_socketNODELAY(True)
        dev.set_socketRetryLimit(self.socket_retry_limit)
        dev.set_socketTimeout(self.socket_timeout)
        return dev

    def _is_valid_status(self, status):
        return (
            isinstance(status, dict)
            and status.get("Err") is None
            and isinstance(status.get("dps"), dict)
        )

    def _discover_ip(self):
        try:
            scanned = tinytuya.deviceScan(False, self.discovery_timeout)
            if isinstance(scanned, dict):
                for ip, info in scanned.items():
                    if not isinstance(info, dict):
                        continue
                    gwid = info.get("gwId") or info.get("id")
                    scanned_mac = str(info.get("mac", "")).lower()
                    if gwid == self.device_id or (self.mac and scanned_mac == self.mac):
                        return ip
        except Exception as exc:
            self._log(f"deviceScan() falló: {exc}")
        return self._cached_ip()

    def _get_working(self, force_discovery=False):
        candidates = []
        if force_discovery:
            candidates.append(self._discover_ip())
        candidates.extend([self._cached_ip(), self.default_ip])

        seen = set()
        last_error = None
        for ip in candidates:
            if not ip or ip in seen:
                continue
            seen.add(ip)
            try:
                dev = self._build_device(ip)
                status = dev.status()
                self._log(f"status({ip}) => {status}")
                if self._is_valid_status(status):
                    self._save_cache({"ip": ip, "updated_at": int(time.time()), "mac": self.mac})
                    return dev, ip, status
                last_error = status
            except Exception as exc:
                last_error = str(exc)
                self._log(f"Error probando IP {ip}: {exc}")
        raise RuntimeError(f"No se pudo conectar a {self.name}. Último error: {last_error}")

    def _execute_switch(self, value: bool):
        try:
            dev, ip, before = self._get_working(force_discovery=False)
        except Exception:
            dev, ip, before = self._get_working(force_discovery=True)

        result = {
            "ok": False,
            "sent": False,
            "confirmed": False,
            "classification": "failed",
            "ip": ip,
            "state_before": before,
            "state_after": None,
            "failure_reason": None,
            "error": None,
        }

        try:
            if value:
                dev.turn_on()
            else:
                dev.turn_off()
            result["sent"] = True
        except Exception as exc:
            result["error"] = f"send_failed: {exc}"
            result["failure_reason"] = "transport_error"
            result["classification"] = "failed"
            return result

        time.sleep(self.confirm_delay)
        try:
            after = dev.status()
            result["state_after"] = after
            confirmed = self._is_valid_status(after) and bool(after.get("dps", {}).get(self.dps_switch)) is value
            result["confirmed"] = confirmed
            result["ok"] = confirmed
            result["classification"] = "confirmed" if confirmed else "sent_but_unconfirmed"
            result["failure_reason"] = None if confirmed else "mismatch"
        except Exception as exc:
            result["error"] = f"confirm_failed: {exc}"
            result["failure_reason"] = "transport_error"
            result["classification"] = "transport_error"
        return result

    def get_status(self, rid=None):
        with self.device_lock:
            _, ip, status = self._get_working(force_discovery=False)
            return {"ok": True, "ip": ip, "status": status}

    def turn_on(self, rid=None):
        with self.device_lock:
            return self._execute_switch(True)

    def turn_off(self, rid=None):
        with self.device_lock:
            return self._execute_switch(False)

    def restore_previous_state(self, rid=None):
        return {"ok": False, "error": "unsupported_capability", "classification": "failed"}

    def restore_current_state(self, rid=None):
        return {"ok": False, "error": "unsupported_capability", "classification": "failed"}
