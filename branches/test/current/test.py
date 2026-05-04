VERSION = "1.0.0"
DESCRIPTION = "Plugin de prueba simple"
TRIGGERS = ["test", "prueba"]

def can_handle(prompt):
    prompt = prompt.lower()
    return any(t in prompt for t in TRIGGERS)

def handle(prompt):
    return {
        "respuesta": "ok",
        "cerebro": "test"
    }
