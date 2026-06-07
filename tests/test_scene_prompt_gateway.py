import base64
import time
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

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

    def test_device_session_requires_native_signature(self):
        token = core.issue_session_token("phone-1", "PEARL Client", device_public_key="public-key")

        with patch.object(core.requests, "request") as request_call:
            response = self.client.get(
                "/api/v1/scene-prompts/pending",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "device_signature_required")
        request_call.assert_not_called()

    def test_signed_device_session_is_proxied_to_hub(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        token = core.issue_session_token(
            "phone-1",
            "PEARL Client",
            device_public_key=base64.b64encode(public_key).decode("ascii"),
        )
        timestamp = str(int(time.time()))
        nonce = "nonce-1"
        signing_payload = "\n".join([
            "GET",
            "/api/v1/scene-prompts/pending",
            timestamp,
            nonce,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ])
        signature = private_key.sign(
            signing_payload.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        hub_response = Mock(status_code=200)
        hub_response.json.return_value = {"status": "ok", "prompts": []}

        with patch.object(core.requests, "request", return_value=hub_response) as request_call:
            response = self.client.get(
                "/api/v1/scene-prompts/pending",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-PEARL-Device-Id": "phone-1",
                    "X-PEARL-Timestamp": timestamp,
                    "X-PEARL-Nonce": nonce,
                    "X-PEARL-Signature": base64.b64encode(signature).decode("ascii"),
                },
            )

        self.assertEqual(response.status_code, 200)
        forwarded_headers = request_call.call_args.kwargs["headers"]
        self.assertEqual(forwarded_headers["X-PEARL-Device-Id"], "phone-1")
        self.assertEqual(forwarded_headers["X-PEARL-Device-Name"], "PEARL Client")

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
