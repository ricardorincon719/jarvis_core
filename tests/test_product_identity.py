import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import unittest

from device_sessions import DeviceSessionStore

import os
os.environ.setdefault("JARVIS_SECRET_TOKEN", "test-master-token-0123456789abcdef")
import core


class ProductIdentityTest(unittest.TestCase):
    def setUp(self):
        core.app.config.update(TESTING=True)
        self.client = core.app.test_client()
        self.headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}

    def test_default_identity_marks_lite_beta(self):
        identity = core.product_identity()

        self.assertEqual(identity["edition"], "lite")
        self.assertEqual(identity["api_version"], "v1")
        self.assertTrue(identity["version"].startswith("0.7.0-beta."))

    def test_core_has_no_laptop_execution_guard(self):
        self.assertFalse(hasattr(core, "guard_core_execution"))
        self.assertFalse(hasattr(core, "CORE_DEV_MODE"))

    def test_versioned_health_alias_preserves_authorization(self):
        response = self.client.get("/api/v1/health", headers=self.headers)
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "online")
        self.assertEqual(payload["product"]["edition"], "lite")

    def test_device_session_can_be_validated_and_revoked_via_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DeviceSessionStore(Path(temp_dir) / "sessions.json", ttl_seconds=100)
            token = store.issue("phone-1", "PEARL Client")
            headers = {"Authorization": f"Bearer {token}"}

            with patch.object(core, "device_session_store", store):
                validation = self.client.get("/api/v1/auth/session", headers=headers)
                logout = self.client.post("/api/v1/auth/logout", headers=headers)
                after_logout = self.client.get("/api/v1/auth/session", headers=headers)

            self.assertEqual(validation.status_code, 200)
            self.assertEqual(validation.get_json()["session"]["device_id"], "phone-1")
            self.assertEqual(logout.status_code, 200)
            self.assertEqual(after_logout.status_code, 403)

    def test_master_token_cannot_be_revoked_by_logout_endpoint(self):
        response = self.client.post("/api/v1/auth/logout", headers=self.headers)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "device_session_required")

    def test_pin_auth_issues_persistent_device_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sessions.json"
            store = DeviceSessionStore(path, ttl_seconds=100)
            auth_plugin = {"module": SimpleNamespace(authenticate=lambda pin: pin == "1234")}

            with patch.object(core, "device_session_store", store), patch.dict(
                core.plugins,
                {"auth": auth_plugin},
                clear=True,
            ):
                response = self.client.post(
                    "/api/v1/auth/pin",
                    json={"pin": "1234", "device_id": "phone-1", "device_name": "PEARL Client"},
                )

            payload = response.get_json()
            token = payload["token"].removeprefix("Bearer ")
            reloaded_store = DeviceSessionStore(path, ttl_seconds=100)

            self.assertEqual(response.status_code, 200)
            session = reloaded_store.validate(token)
            self.assertEqual(session["device_id"], "phone-1")
            self.assertEqual(session["audience"], "pearl-client")
            self.assertEqual(
                set(session["scopes"]),
                {"pearl.ask", "jinnex.query", "jinnex.memory.decide"},
            )

    def test_watch_pairing_issues_fixed_audience_and_scopes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DeviceSessionStore(Path(temp_dir) / "sessions.json", ttl_seconds=100)
            auth_plugin = {"module": SimpleNamespace(authenticate=lambda pin: pin == "1234")}
            headers = {"X-Jinnex-Client-Key": "a" * 64}
            with patch.object(core, "device_session_store", store), patch.dict(
                core.plugins, {"auth": auth_plugin}, clear=True
            ):
                response = self.client.post(
                    "/api/v1/auth/jinnex-watch",
                    json={"pin": "1234", "device_id": "watch-1",
                          "device_name": "Jarvis Watch", "device_public_key": "public-key"},
                    headers=headers,
                )

            payload = response.get_json()
            session = store.validate(payload["token"].removeprefix("Bearer "))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(session["audience"], "jinnex-watch")
            self.assertEqual(set(session["scopes"]), set(core.JINNEX_WATCH_SCOPES))

    def test_watch_pairing_lockout_isolated_by_trusted_ingress_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DeviceSessionStore(Path(temp_dir) / "sessions.json", ttl_seconds=100)
            auth_plugin = {"module": SimpleNamespace(authenticate=lambda pin: False)}
            payload = {"pin": "bad", "device_id": "watch-1",
                       "device_name": "Jarvis Watch", "device_public_key": "public-key"}
            with patch.object(core, "device_session_store", store), patch.dict(
                core.plugins, {"auth": auth_plugin}, clear=True
            ), patch.object(core, "auth_failures", {}):
                for _ in range(core.AUTH_MAX_ATTEMPTS):
                    first = self.client.post(
                        "/api/v1/auth/jinnex-watch", json=payload,
                        headers={"X-Jinnex-Client-Key": "a" * 64})
                blocked = self.client.post(
                    "/api/v1/auth/jinnex-watch", json=payload,
                    headers={"X-Jinnex-Client-Key": "a" * 64})
                independent = self.client.post(
                    "/api/v1/auth/jinnex-watch", json=payload,
                    headers={"X-Jinnex-Client-Key": "b" * 64})

            self.assertEqual(first.status_code, 403)
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(independent.status_code, 403)

if __name__ == "__main__":
    unittest.main()
