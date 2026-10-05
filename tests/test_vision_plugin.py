import unittest
from unittest import mock

import requests

from branches.vision.current import plugin as vision
from router import route_query


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class VisionRoutingTest(unittest.TestCase):
    def setUp(self):
        self.plugins = ["domotica", "music", "music_local", "local_ia", "vision"]

    def test_look_requests_route_to_vision_even_with_assistant_name(self):
        prompts = [
            "¿cómo me veo?",
            "Jarvis, ¿cómo me veo?",
            "jarvis mírame",
            "qué ves",
            "cómo estoy",
            "Jarvis, ¿cómo he estado?",
            "deja de mirarme",
            "vuelve a mirarme",
            "apaga la cámara",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_query(prompt, self.plugins), "vision")

    def test_unrelated_requests_do_not_route_to_vision(self):
        cases = {
            "apaga la luz de la sala": "domotica",
            "reproduce música lofi": "music",
            "Jarvis, ¿cómo estás?": "local_ia",
            "Jarvis, qué hora es": "local_ia",
            "cómo estoy de batería en el celular": None,
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                routed = route_query(prompt, self.plugins)
                self.assertNotEqual(routed, "vision")
                if expected:
                    self.assertEqual(routed, expected)

    def test_vision_not_selected_when_plugin_not_loaded(self):
        plugins = ["domotica", "music", "local_ia"]
        self.assertEqual(route_query("Jarvis, ¿cómo me veo?", plugins), "local_ia")


class VisionIntentTest(unittest.TestCase):
    def test_intents(self):
        cases = {
            "¿cómo me veo?": "look",
            "mírame": "look",
            "¿cómo he estado?": "summary",
            "cuánto llevo frente a la laptop": "summary",
            "deja de mirarme": "pause",
            "pausa la cámara": "pause",
            "vuelve a mirarme": "resume",
            "activa la cámara": "resume",
            "pon música": None,
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(vision.detect_intent(prompt), expected)


class VisionHandleTest(unittest.TestCase):
    def test_look_returns_remote_description(self):
        payload = {
            "status": "ok",
            "signals": {"present": True, "owner": True, "light": "normal"},
            "description": "Señor, se le ve atento.",
        }
        with mock.patch.object(vision.requests, "post", return_value=FakeResponse(200, payload)) as post:
            response = vision.handle("¿cómo me veo?")
        self.assertEqual(response["respuesta"], "Señor, se le ve atento.")
        self.assertTrue(response["ok"])
        self.assertEqual(post.call_args.kwargs["json"], {"describe": True})

    def test_look_without_person(self):
        payload = {"status": "ok", "signals": {"present": False, "light": "normal"}}
        with mock.patch.object(vision.requests, "post", return_value=FakeResponse(200, payload)):
            response = vision.handle("mírame")
        self.assertIn("No lo veo", response["respuesta"])

    def test_look_unknown_person_does_not_describe(self):
        payload = {
            "status": "ok",
            "signals": {"present": True, "owner": False, "light": "normal"},
            "description": "Descripción que no debe leerse.",
        }
        with mock.patch.object(vision.requests, "post", return_value=FakeResponse(200, payload)):
            response = vision.handle("¿cómo me veo?")
        self.assertIn("no lo reconozco", response["respuesta"])
        self.assertNotIn("no debe leerse", response["respuesta"])

    def test_look_falls_back_to_local_signals(self):
        payload = {
            "status": "ok",
            "signals": {"present": True, "owner": True, "light": "oscuro"},
            "description_error": "OpenRouter respondió 500.",
        }
        with mock.patch.object(vision.requests, "post", return_value=FakeResponse(200, payload)):
            response = vision.handle("¿cómo me veo?")
        self.assertIn("muy poca luz", response["respuesta"])

    def test_camera_busy(self):
        payload = {"status": "busy", "error": "ocupada"}
        with mock.patch.object(vision.requests, "post", return_value=FakeResponse(409, payload)):
            response = vision.handle("mírame")
        self.assertFalse(response["ok"])
        self.assertIn("ocupada", response["respuesta"])

    def test_camera_failed_asks_to_reconnect(self):
        payload = {"status": "camera_failed", "error": "La cámara no respondió a tiempo."}
        with mock.patch.object(vision.requests, "post", return_value=FakeResponse(503, payload)):
            response = vision.handle("¿cómo me veo?")
        self.assertFalse(response["ok"])
        self.assertIn("Desconéctela", response["respuesta"])

    def test_service_down(self):
        with mock.patch.object(vision.requests, "post", side_effect=requests.ConnectionError("down")):
            response = vision.handle("mírame")
        self.assertFalse(response["ok"])
        self.assertIn("no responde", response["respuesta"])

    def test_summary(self):
        payload = {"status": "ok", "summary": {
            "checks": 12, "present_checks": 10, "dark_checks": 2,
            "current_session_minutes": 135, "monitor_enabled": True,
        }}
        with mock.patch.object(vision.requests, "get", return_value=FakeResponse(200, payload)):
            response = vision.handle("¿cómo he estado?")
        self.assertIn("2 horas y 15 minutos", response["respuesta"])
        self.assertIn("10 de 12", response["respuesta"])
        self.assertIn("2 de ellos con muy poca luz", response["respuesta"])

    def test_pause_and_resume(self):
        with mock.patch.object(vision.requests, "post", return_value=FakeResponse(200, {"status": "ok"})) as post:
            paused = vision.handle("deja de mirarme")
            resumed = vision.handle("vuelve a mirarme")
        self.assertEqual(post.call_args_list[0].kwargs["json"], {"enabled": False})
        self.assertEqual(post.call_args_list[1].kwargs["json"], {"enabled": True})
        self.assertIn("Dejo de mirarlo", paused["respuesta"])
        self.assertIn("Vuelvo a revisar", resumed["respuesta"])


if __name__ == "__main__":
    unittest.main()
