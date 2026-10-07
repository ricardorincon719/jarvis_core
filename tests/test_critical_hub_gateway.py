import unittest
from unittest import mock

from branches.critical.current import plugin as critical


class CriticalHubGatewayTest(unittest.TestCase):
    def test_process_request_sends_core_gateway_token(self):
        response = mock.MagicMock(status_code=200)
        response.json.return_value = {"status": "success", "response": "Listo."}

        with mock.patch.object(
            critical, "HUB_HEADERS", {"X-PEARL-Core-Gateway": "secret"}
        ), mock.patch.object(critical.requests, "post", return_value=response) as post:
            critical.handle("analiza el sistema")

        hub_call = post.call_args_list[0]
        self.assertTrue(hub_call.args[0].endswith("/process"))
        self.assertEqual(
            hub_call.kwargs["headers"].get("X-PEARL-Core-Gateway"), "secret"
        )


if __name__ == "__main__":
    unittest.main()
