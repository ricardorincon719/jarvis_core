"""
Plugin AUTH - Autenticación por PIN
"""

NAME = "auth"
VERSION = "v1.0.0"
DESCRIPTION = "Autenticación por PIN"
PIN_CORRECTO = "1234"

# Función requerida por el core (aunque no se use desde /ask)
def handle(prompt):
    """Manejo por defecto (no usado directamente)"""
    return {'respuesta': 'Plugin de autenticación', 'cerebro': NAME}

# Función específica para autenticación
def authenticate(pin):
    return pin == PIN_CORRECTO
