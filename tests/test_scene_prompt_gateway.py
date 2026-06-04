import unittest
from unittest.mock import Mock, patch

import core


class ScenePromptGatewayTest(unittest.TestCase):
    def setUp(self):
        core.app.config.update(TESTING=True)
        self.client = core.app.test_client()
        self.headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}

    def test_pending_prompts_are_proxied_to_hub(self):
        hub_response = Mock(status_code=200)
        hub_response.json.return_value = {"status": "ok", "prompts": []}

        with patch.object(core.requests, "request", return_value=hub_response) as request_call:
            response = self.client.get(
                "/api/v1/scene-prompts/pending?kind=candidate_approval",
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["prompts"], [])
        request_call.assert_called_once_with(
            "GET",
            f"{core.HUB_URL}/api/v1/scene-prompts/pending",
            json=None,
            params={"kind": "candidate_approval"},
            timeout=(3, core.HUB_API_TIMEOUT),
        )

    def test_decision_is_proxied_to_hub(self):
        hub_response = Mock(status_code=200)
        hub_response.json.return_value = {"status": "ok", "executed": False}
        decision = {"decision": "accept", "idempotency_key": "decision-1"}

        with patch.object(core.requests, "request", return_value=hub_response) as request_call:
            response = self.client.post(
                "/api/v1/scene-prompts/prompt-1/decision",
                headers=self.headers,
                json=decision,
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["executed"])
        request_call.assert_called_once_with(
            "POST",
            f"{core.HUB_URL}/api/v1/scene-prompts/prompt-1/decision",
            json=decision,
            params=None,
            timeout=(3, core.HUB_API_TIMEOUT),
        )

    def test_gateway_requires_authorization(self):
        with patch.object(core.requests, "request") as request_call:
            response = self.client.get("/api/v1/scene-prompts/pending")

        self.assertEqual(response.status_code, 403)
        request_call.assert_not_called()

    def test_gateway_reports_hub_unavailable(self):
        with patch.object(core.requests, "request", side_effect=core.requests.ConnectionError("offline")):
            response = self.client.get("/api/v1/scene-prompts/pending", headers=self.headers)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "hub_unavailable")


if __name__ == "__main__":
    unittest.main()
