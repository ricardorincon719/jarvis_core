from branches.domotica.config import get_device
from branches.domotica.config import list_devices
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
