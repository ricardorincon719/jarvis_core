import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import unittest
from unittest.mock import MagicMock, patch

from branches.music.agent import MusicNodeClient


class MusicNodeClientTest(unittest.TestCase):
    @patch("branches.music.agent.requests")
    def test_sends_bearer_token_on_every_request(self, requests):
        requests.get.return_value = MagicMock(json=lambda: {"status": "ok"})
        requests.post.return_value = MagicMock(json=lambda: {"status": "ok"})
        client = MusicNodeClient(host="nodo", port=5005, token="secreto")

        client.get("/status")
        client.post("/pause")

        expected = {"Authorization": "Bearer secreto"}
        self.assertEqual(requests.get.call_args.kwargs["headers"], expected)
        self.assertEqual(requests.post.call_args.kwargs["headers"], expected)

    @patch("branches.music.agent.requests")
    def test_sends_no_authorization_header_without_token(self, requests):
        requests.get.return_value = MagicMock(json=lambda: {"status": "ok"})

        MusicNodeClient(host="nodo", port=5005, token="").get("/status")

        self.assertEqual(requests.get.call_args.kwargs["headers"], {})


if __name__ == "__main__":
    unittest.main()
