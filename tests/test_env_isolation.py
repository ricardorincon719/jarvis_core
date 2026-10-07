import isolated_env

import os
import unittest

import core


class EnvIsolationTest(unittest.TestCase):
    def test_real_env_file_is_never_loaded(self):
        # Si falla, algún test importó core antes que isolated_env.
        self.assertEqual(os.environ.get("JARVIS_ENV_FILE"), "")
        self.assertIsNone(core.ENV_FILE_LOADED)

    def test_no_inherited_secrets_reach_the_tests(self):
        leaked = sorted(
            name
            for name in os.environ
            if isolated_env.SENSITIVE_NAME.search(name)
            and name not in isolated_env.TEST_ENV
        )
        # Solo nombres, nunca valores, para no imprimir secretos al fallar.
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
