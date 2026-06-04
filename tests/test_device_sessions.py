import json
import tempfile
import unittest
from pathlib import Path

from device_sessions import DeviceSessionStore


class DeviceSessionStoreTest(unittest.TestCase):
    def test_session_survives_new_store_instance_without_storing_raw_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "device_sessions.json"
            first_store = DeviceSessionStore(path, ttl_seconds=100, now_fn=lambda: 1000)
            token = first_store.issue("phone-1", "PEARL Client")

            second_store = DeviceSessionStore(path, ttl_seconds=100, now_fn=lambda: 1050)
            session = second_store.validate(token)
            raw_data = path.read_text(encoding="utf-8")

            self.assertEqual(session["device_id"], "phone-1")
            self.assertNotIn(token, raw_data)
            self.assertEqual(json.loads(raw_data)["schema_version"], 1)

    def test_session_expires_and_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "device_sessions.json"
            store = DeviceSessionStore(path, ttl_seconds=10, now_fn=lambda: 1000)
            token = store.issue("phone-1", "PEARL Client")

            expired_store = DeviceSessionStore(path, ttl_seconds=10, now_fn=lambda: 1011)

            self.assertIsNone(expired_store.validate(token))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["sessions"], {})

    def test_session_can_be_revoked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "device_sessions.json"
            store = DeviceSessionStore(path, ttl_seconds=100, now_fn=lambda: 1000)
            token = store.issue("phone-1", "PEARL Client")

            self.assertTrue(store.revoke(token))
            self.assertIsNone(store.validate(token))

    def test_session_limit_keeps_most_recent_devices(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "device_sessions.json"
            now = [1000]
            store = DeviceSessionStore(path, ttl_seconds=100, max_sessions=2, now_fn=lambda: now[0])
            first = store.issue("phone-1")
            now[0] += 1
            second = store.issue("phone-2")
            now[0] += 1
            third = store.issue("phone-3")

            self.assertIsNone(store.validate(first))
            self.assertIsNotNone(store.validate(second))
            self.assertIsNotNone(store.validate(third))


    def test_corrupt_session_entry_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "device_sessions.json"
            path.write_text(
                json.dumps({"schema_version": 1, "sessions": {"bad": {"expires_at": "invalid"}}}),
                encoding="utf-8",
            )
            store = DeviceSessionStore(path, ttl_seconds=100, now_fn=lambda: 1000)

            self.assertEqual(store.prune(), 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["sessions"], {})

if __name__ == "__main__":
    unittest.main()
