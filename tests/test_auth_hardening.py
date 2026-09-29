import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("JARVIS_SECRET_TOKEN", "test-master-token-0123456789abcdef")
import core
from device_sessions import DeviceSessionStore


BASE_DIR = Path(__file__).resolve().parents[1]


def load_auth_plugin():
    spec = importlib.util.spec_from_file_location(
        "auth_plugin_under_test",
        BASE_DIR / "branches" / "auth" / "v1.0.0" / "plugin.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MasterTokenTest(unittest.TestCase):
    def test_published_short_or_missing_tokens_are_disabled(self):
        for value in ("", "jarvis_local_123", "corto", "x" * 31):
            self.assertEqual(core.configured_master_token(value), "")

    def test_strong_token_is_accepted(self):
        token = "a" * 64
        self.assertEqual(core.configured_master_token(f"  {token}  "), token)

    def test_disabled_master_token_never_matches(self):
        with patch.object(core, "SECRET_TOKEN", ""):
            self.assertFalse(core.is_master_token(""))
            self.assertFalse(core.is_master_token("jarvis_local_123"))
            response = core.app.test_client().get(
                "/health", headers={"Authorization": "Bearer jarvis_local_123"}
            )
        self.assertEqual(response.status_code, 403)


class AuthPluginTest(unittest.TestCase):
    def test_missing_or_weak_pin_rejects_everything(self):
        for value in ("", "1234", "123456", "12345"):
            with patch.dict(os.environ, {"JARVIS_AUTH_PIN": value}):
                plugin = load_auth_plugin()
                self.assertFalse(plugin.authenticate(value))
                self.assertFalse(plugin.authenticate("1234"))

    def test_configured_pin_is_required(self):
        with patch.dict(os.environ, {"JARVIS_AUTH_PIN": "482915"}):
            plugin = load_auth_plugin()
            self.assertTrue(plugin.authenticate("482915"))
            self.assertTrue(plugin.authenticate(" 482915 "))
            self.assertFalse(plugin.authenticate("482916"))
            self.assertFalse(plugin.authenticate(482915))


class TunnelLockoutTest(unittest.TestCase):
    def setUp(self):
        core.app.config.update(TESTING=True)
        self.client = core.app.test_client()

    def test_tunnel_clients_cannot_rotate_lockout_key(self):
        auth_plugin = {"module": SimpleNamespace(authenticate=lambda pin: False)}
        with patch.dict(core.plugins, {"auth": auth_plugin}, clear=True), patch.object(
            core, "auth_failures", {}
        ):
            for attempt in range(core.AUTH_MAX_ATTEMPTS):
                self.client.post(
                    "/api/v1/auth/pin",
                    json={"pin": "000000"},
                    headers={
                        "CF-Connecting-IP": "203.0.113.7",
                        "X-Jinnex-Client-Key": f"{attempt:064x}",
                    },
                )
            blocked = self.client.post(
                "/api/v1/auth/pin",
                json={"pin": "000000"},
                headers={
                    "CF-Connecting-IP": "203.0.113.7",
                    "X-Jinnex-Client-Key": "f" * 64,
                },
            )
            other_client = self.client.post(
                "/api/v1/auth/pin",
                json={"pin": "000000"},
                headers={"CF-Connecting-IP": "198.51.100.9"},
            )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(other_client.status_code, 403)

    def test_watch_pairing_rejects_tunnel_traffic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DeviceSessionStore(Path(temp_dir) / "sessions.json", ttl_seconds=100)
            auth_plugin = {"module": SimpleNamespace(authenticate=lambda pin: True)}
            with patch.object(core, "device_session_store", store), patch.dict(
                core.plugins, {"auth": auth_plugin}, clear=True
            ):
                response = self.client.post(
                    "/api/v1/auth/jinnex-watch",
                    json={"pin": "482915", "device_id": "watch-1",
                          "device_public_key": "public-key"},
                    headers={"CF-Connecting-IP": "203.0.113.7"},
                )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("token", response.get_json())


if __name__ == "__main__":
    unittest.main()
