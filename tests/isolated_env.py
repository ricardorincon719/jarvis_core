"""Aislamiento del entorno: importar antes que core o cualquier plugin.

Las pruebas nunca deben ver secretos reales: ni los del .env (core.py consulta
JARVIS_ENV_FILE al importarse; vacío desactiva la carga) ni los que exporta el
shell del usuario (OPENROUTER_API_KEY, GEMINI_API_KEY, ...).
"""

import os
import re

SENSITIVE_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PIN)$")
TEST_ENV = {
    "JARVIS_ENV_FILE": "",
    "JARVIS_SECRET_TOKEN": "test-master-token-0123456789abcdef",
}

for name in [name for name in os.environ if SENSITIVE_NAME.search(name)]:
    del os.environ[name]
os.environ.update(TEST_ENV)
