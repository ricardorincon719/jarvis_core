import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SENSITIVE_EXAMPLE_KEYS = {
    "JARVIS_SECRET_TOKEN",
    "JARVIS_AUTH_PIN",
    "JARVIS_MUSIC_TOKEN",
    "SERPAPI_KEY",
    "TUYA_CLOUD_ACCESS_ID",
    "TUYA_CLOUD_ACCESS_KEY",
}


class EnvExampleSecretsTest(unittest.TestCase):
    def test_provider_credentials_are_blank(self):
        values = {}
        for line in (BASE_DIR / ".env.example").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

        for key in SENSITIVE_EXAMPLE_KEYS:
            self.assertIn(key, values)
            self.assertEqual(values[key], "", f"{key} must stay blank in .env.example")


if __name__ == "__main__":
    unittest.main()
