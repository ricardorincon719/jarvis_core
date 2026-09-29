"""
Plugin AUTH - Autenticación por PIN
"""

import hmac
import os

NAME = "auth"
VERSION = "v1.1.0"
DESCRIPTION = "Autenticación por PIN"
MIN_PIN_LENGTH = 6
INSECURE_PINS = frozenset({"1234", "0000", "123456", "000000", "111111"})


def configured_pin() -> str:
    """PIN de JARVIS_AUTH_PIN; vacío (acceso cerrado) si falta o es débil."""
    pin = os.getenv("JARVIS_AUTH_PIN", "").strip()
    if len(pin) < MIN_PIN_LENGTH or pin in INSECURE_PINS:
        return ""
    return pin


if not configured_pin():
    print(
        "⚠️ JARVIS_AUTH_PIN ausente o débil: el emparejamiento por PIN está deshabilitado. "
        f"Define un PIN de al menos {MIN_PIN_LENGTH} caracteres en .env."
    )


# Función requerida por el core (aunque no se use desde /ask)
def handle(prompt):
    """Manejo por defecto (no usado directamente)"""
    return {'respuesta': 'Plugin de autenticación', 'cerebro': NAME}


# Función específica para autenticación
def authenticate(pin):
    expected = configured_pin()
    if not expected or not isinstance(pin, str):
        return False
    return hmac.compare_digest(pin.strip().encode("utf-8"), expected.encode("utf-8"))
