from concurrent.futures import ThreadPoolExecutor, as_completed

from branches.domotica.config import get_device
from branches.domotica.config import list_devices
from branches.domotica.config import update_device_local_key
from branches.domotica.discovery import (
    approve_pending_device,
    discover_tuya_devices,
    list_pending_devices,
    reject_pending_device,
)
from branches.domotica.registry import get_driver_class


class DomoticaService:
    def devices(self):
        return list_devices(include_secrets=False)

    def discover_devices(self, timeout=None):
        return discover_tuya_devices(timeout=timeout)

    def pending_devices(self):
        return list_pending_devices()

    def approve_device(self, candidate_id: str, local_key: str = "", name: str = "", room: str = ""):
        return approve_pending_device(candidate_id, local_key=local_key, name=name, room=room)

    def reject_device(self, candidate_id: str):
        return reject_pending_device(candidate_id)

    def get_driver(self, device_name: str):
        cfg = get_device(device_name)
        if not cfg:
            raise ValueError(f"Dispositivo no encontrado: {device_name}")

        driver_name = cfg.get("driver")
        driver_cls = get_driver_class(driver_name)
        return driver_cls(cfg)

    def status(self, device_name: str):
        driver = self.get_driver(device_name)
        return driver.get_status()

    def statuses(self):
        devices = list_devices(include_secrets=False)
        enabled = [name for name, cfg in devices.items() if cfg.get("enabled") is not False]
        if not enabled:
            return {}

        results = {}
        workers = min(4, len(enabled))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._probe_status, name): name for name in enabled}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    results[name] = self._offline_status(str(exc))
        return results

    def _probe_status(self, device_name: str):
        cfg = get_device(device_name) or {}
        driver = self.get_driver(device_name)
        result = driver.probe_status() if hasattr(driver, "probe_status") else driver.get_status()
        if not result.get("ok"):
            return self._offline_status(
                result.get("error") or "device_unreachable",
                ip=result.get("ip"),
                error_code=result.get("error_code"),
            )

        raw = result.get("status") or {}
        dps = raw.get("dps") if isinstance(raw, dict) else {}
        dps = dps if isinstance(dps, dict) else {}
        switch_key = str(cfg.get("dps_switch") or ("1" if cfg.get("type") == "plug" else "20"))
        switch = dps.get(switch_key)
        return {
            "available": True,
            "state": "on" if bool(switch) else "off",
            "switch": bool(switch),
            "ip": result.get("ip") or cfg.get("ip"),
            "needs_relink": False,
        }

    @staticmethod
    def _offline_status(error: str, ip=None, error_code=None):
        error = str(error or "device_unreachable")
        code = str(error_code or "")
        needs_relink = code == "904" or "904" in error or "Unexpected Payload" in error
        return {
            "available": False,
            "state": "offline",
            "switch": None,
            "ip": ip,
            "needs_relink": needs_relink,
            "error": "local_key_invalid" if needs_relink else "device_unreachable",
        }

    def update_local_key(self, device_name: str, local_key: str):
        updated = update_device_local_key(device_name, local_key)
        return {
            "device_name": device_name,
            "device": {
                **updated,
                "local_key": "***",
                "has_local_key": True,
            },
        }

    def turn_on(self, device_name: str):
        driver = self.get_driver(device_name)
        return driver.turn_on()

    def turn_off(self, device_name: str):
        driver = self.get_driver(device_name)
        return driver.turn_off()

    def apply_scene(self, device_name: str, scene: dict):
        driver = self.get_driver(device_name)
        return driver.apply_scene(scene)

    def restore_previous_state(self, device_name: str):
        driver = self.get_driver(device_name)
        return driver.restore_previous_state()

    def restore_current_state(self, device_name: str):
        driver = self.get_driver(device_name)
        return driver.restore_current_state()
