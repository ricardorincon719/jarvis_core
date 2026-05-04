VERSION = "1.0.0"
DESCRIPTION = "Control de lámpara Tuya local (Steck)"
TRIGGERS = ["luz", "lampara", "lámpara", "cuarto"]

import tinytuya

DEVICE_ID = "3483408310521cf4c753"
DEVICE_IP = "192.168.100.100"
LOCAL_KEY = "k~)0B|~.=~[(U!p@"

d = tinytuya.BulbDevice(DEVICE_ID, DEVICE_IP, LOCAL_KEY)
d.set_version(3.3)


def can_handle(pregunta):
    p = pregunta.lower()
    return any(t in p for t in TRIGGERS)


def handle(pregunta):
    p = pregunta.lower()

    try:
        # ON
        if "prende" in p or "encende" in p or "enciende" in p:
            d.turn_on()
            return {"respuesta": "Lámpara encendida", "cerebro": "SteckLight"}

        # OFF
        if "apaga" in p:
            d.turn_off()
            return {"respuesta": "Lámpara apagada", "cerebro": "SteckLight"}

        # BRILLO
        if "brillo" in p:
            if "max" in p:
                d.set_brightness(1000)
                return {"respuesta": "Brillo al máximo", "cerebro": "SteckLight"}
            if "min" in p:
                d.set_brightness(100)
                return {"respuesta": "Brillo bajo", "cerebro": "SteckLight"}

        # TEMPERATURA
        if "calida" in p or "cálida" in p:
            d.set_mode("white")
            d.set_colourtemp(1000)
            return {"respuesta": "Luz cálida", "cerebro": "SteckLight"}

        if "fria" in p or "fría" in p:
            d.set_mode("white")
            d.set_colourtemp(0)
            return {"respuesta": "Luz fría", "cerebro": "SteckLight"}

        # COLOR
        if "rojo" in p:
            d.set_mode("colour")
            d.set_colour(1000, 0, 0)
            return {"respuesta": "Luz roja", "cerebro": "SteckLight"}

        if "azul" in p:
            d.set_mode("colour")
            d.set_colour(0, 0, 1000)
            return {"respuesta": "Luz azul", "cerebro": "SteckLight"}

        if "verde" in p:
            d.set_mode("colour")
            d.set_colour(0, 1000, 0)
            return {"respuesta": "Luz verde", "cerebro": "SteckLight"}

        return {
            "respuesta": "Entendí que es para la lámpara pero no reconocí la acción",
            "cerebro": "SteckLight"
        }

    except Exception as e:
        return {
            "respuesta": f"Error controlando la lámpara: {e}",
            "cerebro": "SteckLight"
        }
