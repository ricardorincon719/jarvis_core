import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branches.domotica import config, discovery
from branches.domotica.service import DomoticaService


class DiscoveryRefreshTest(unittest.TestCase):
    def test_known_device_accepts_new_private_ip(self):
        devices = {
            "lamp_sala": {
                "name": "lamp_sala",
                "device_id": "device-1",
                "ip": "192.168.1.10",
                "local_key": "old-key",
            }
        }
        candidate = {
            "device_id": "device-1",
            "ip": "192.168.1.44",
            "mac": "aa:bb:cc:dd:ee:ff",
        }

        with patch.object(discovery, "upsert_device") as upsert:
            changed = discovery._refresh_known_device(candidate, devices)

        self.assertTrue(changed)
        self.assertEqual(upsert.call_args.args[1]["ip"], "192.168.1.44")

    def test_cloud_key_replaces_stale_key_after_repair(self):
        devices = {
            "lamp_sala": {
                "name": "lamp_sala",
                "device_id": "device-1",
                "ip": "192.168.1.10",
                "local_key": "old-key",
            }
        }
        candidate = {
            "device_id": "device-1",
            "ip": "192.168.1.10",
            "local_key": "new-key",
            "cloud_synced": True,
        }

        with patch.object(discovery, "upsert_device") as upsert:
            changed = discovery._refresh_known_device(candidate, devices)

        self.assertTrue(changed)
        self.assertEqual(upsert.call_args.args[1]["local_key"], "new-key")


class DeviceConfigRepairTest(unittest.TestCase):
    def test_manual_key_update_preserves_device_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "devices.json"
            original = {
                "lamp_sala": {
                    "name": "lamp_sala",
                    "label": "Lámpara Sala",
                    "room": "sala",
                    "type": "light",
                    "driver": "tuya_light",
                    "device_id": "device-1",
                    "local_key": "old-key",
                    "ip": "192.168.1.10",
                }
            }
            with patch.object(config, "CONFIG_FILE", config_file), patch.object(config, "DEFAULT_DEVICES", original):
                updated = config.update_device_local_key("lamp_sala", "new-key")

            self.assertEqual(updated["name"], "lamp_sala")
            self.assertEqual(updated["device_id"], "device-1")
            self.assertEqual(updated["local_key"], "new-key")


class FakeDriver:
    def __init__(self, result):
        self.result = result

    def probe_status(self):
        return self.result


class RuntimeStatusTest(unittest.TestCase):
    def setUp(self):
        self.service = DomoticaService()

    def probe(self, result, device_type="light"):
        cfg = {"name": "lamp", "type": device_type, "driver": "tuya_light"}
        with patch("branches.domotica.service.get_device", return_value=cfg), patch.object(
            self.service, "get_driver", return_value=FakeDriver(result)
        ):
            return self.service._probe_status("lamp")

    def test_reports_real_on_and_off_states(self):
        on = self.probe({"ok": True, "ip": "192.168.1.10", "status": {"dps": {"20": True}}})
        off = self.probe({"ok": True, "ip": "192.168.1.10", "status": {"dps": {"20": False}}})

        self.assertEqual(on["state"], "on")
        self.assertEqual(off["state"], "off")

    def test_error_904_requests_relink_instead_of_showing_active(self):
        status = self.probe({
            "ok": False,
            "ip": "192.168.1.10",
            "error": "Unexpected Payload from Device",
            "error_code": "904",
        })

        self.assertEqual(status["state"], "offline")
        self.assertTrue(status["needs_relink"])
        self.assertEqual(status["error"], "local_key_invalid")


if __name__ == "__main__":
    unittest.main()
