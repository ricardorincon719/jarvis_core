import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import unittest
from unittest.mock import patch

import core


class RouteEndpointTest(unittest.TestCase):
    def setUp(self):
        core.app.config.update(TESTING=True)
        self.client = core.app.test_client()
        self.headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}
        plugins = {name: {"module": object()} for name in ("domotica", "music", "local_ia")}
        plugins_patch = patch.dict(core.plugins, plugins, clear=True)
        plugins_patch.start()
        self.addCleanup(plugins_patch.stop)

    def test_classifies_without_executing(self):
        with patch.object(core, "update_context") as update_context:
            action = self.client.post(
                "/api/v1/route", json={"text": "apaga la luz"}, headers=self.headers)
            chat = self.client.post(
                "/api/v1/route", json={"text": "qué música te gusta"}, headers=self.headers)

        self.assertEqual(action.status_code, 200)
        self.assertEqual(action.get_json()["kind"], "action")
        self.assertEqual(action.get_json()["plugin"], "domotica")
        self.assertEqual(chat.get_json()["kind"], "assistant")
        update_context.assert_not_called()

    def test_requires_authorization(self):
        response = self.client.post("/api/v1/route", json={"text": "apaga la luz"})
        self.assertIn(response.status_code, {401, 403})

    def test_rejects_empty_text(self):
        response = self.client.post("/api/v1/route", json={"text": " "}, headers=self.headers)
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
