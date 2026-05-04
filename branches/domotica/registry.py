from branches.domotica.drivers.tuya_light import TuyaLightDriver

DRIVER_REGISTRY = {
    "tuya_light": TuyaLightDriver,
}


def get_driver_class(driver_name: str):
    driver_cls = DRIVER_REGISTRY.get(driver_name)
    if not driver_cls:
        raise ValueError(f"Driver no soportado: {driver_name}")
    return driver_cls
