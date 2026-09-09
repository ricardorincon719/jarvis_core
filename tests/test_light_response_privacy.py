import unittest

import tuya_light
from branches.comandos.current import plugin as legacy_light


class LightResponsePrivacyTest(unittest.TestCase):
    def setUp(self):
        self.result = {
            "classification": "confirmed",
            "ip": "192.168.1.44",
            "ok": True,
        }

    def assert_private_response(self, response):
        self.assertNotIn(self.result["ip"], response["respuesta"])
        self.assertEqual(response["debug"]["ip"], self.result["ip"])

    def test_standalone_light_response_hides_ip_but_debug_keeps_it(self):
        response = tuya_light.format_response("Luz encendida", "Fallo", self.result)

        self.assert_private_response(response)

    def test_legacy_plugin_response_hides_ip_but_debug_keeps_it(self):
        response = legacy_light.format_response("Luz encendida", "Fallo", self.result)

        self.assert_private_response(response)


if __name__ == "__main__":
    unittest.main()
