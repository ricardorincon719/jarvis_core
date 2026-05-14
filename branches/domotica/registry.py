DRIVER_REGISTRY = {
    "tuya_light": "branches.domotica.drivers.tuya_light:TuyaLightDriver",
    "tuya_plug": "branches.domotica.drivers.tuya_plug:TuyaPlugDriver",
}


def get_driver_class(driver_name: str):
    target = DRIVER_REGISTRY.get(driver_name)
    if not target:
        raise ValueError(f"Driver no soportado: {driver_name}")

    module_name, class_name = target.split(":", 1)
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)
