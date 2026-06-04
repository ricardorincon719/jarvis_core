import unittest

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

    def test_versioned_health_alias_preserves_authorization(self):
        response = self.client.get("/api/v1/health", headers=self.headers)
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "online")
        self.assertEqual(payload["product"]["edition"], "lite")


if __name__ == "__main__":
    unittest.main()
