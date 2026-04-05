"""
Plugin INTERNET - Acciones con internet (simulado)
"""

import requests

NAME = "internet"
VERSION = "v1.0.0"
DESCRIPTION = "Acciones con internet (clima, vuelos, compras)"
TRIGGERS = ["clima", "tiempo", "vuelo", "comprar", "pedir", "noticias"]

def can_handle(prompt):
    prompt_lower = prompt.lower()
    return any(keyword in prompt_lower for keyword in TRIGGERS)

def handle(prompt):
    prompt_lower = prompt.lower()
    
    if "clima" in prompt_lower:
        return {'respuesta': "Clima en Córdoba: 24°C, parcialmente nublado. (API por implementar)", 'cerebro': NAME}
    if "vuelo" in prompt_lower:
        return {'respuesta': "Vuelos a Córdoba disponibles. (API por implementar)", 'cerebro': NAME}
    return {'respuesta': "Función de internet en desarrollo.", 'cerebro': NAME}
