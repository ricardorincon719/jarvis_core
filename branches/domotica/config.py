import json
import os
import re
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent / "devices.json"

DEFAULT_DEVICES = {
    "lamp_quarto": {
        "name": "lamp_quarto",
        "label": "Lámpara Cuarto",
        "room": "cuarto",
        "driver": "tuya_light",
        "provider": "tuya",
        "device_id": os.getenv("JARVIS_TUYA_DEVICE_ID", "3483408310521cf4c753"),
        "local_key": os.getenv("JARVIS_TUYA_LOCAL_KEY", "k~)0B|~.=~[(U!p@"),
        "ip": os.getenv("JARVIS_TUYA_IP", "192.168.100.100"),
        "mac": os.getenv("JARVIS_TUYA_MAC", "10:52:1c:f4:c7:53"),
        "version": float(os.getenv("JARVIS_TUYA_VERSION", "3.3")),
        "enabled": True,
    }
}


def load_devices():
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_DEVICES)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return dict(DEFAULT_DEVICES)

    merged = dict(DEFAULT_DEVICES)
    merged.update(data)
    return merged


def save_devices(devices: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(devices, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, CONFIG_FILE)


def list_devices(include_secrets: bool = False):
    devices = load_devices()
    if include_secrets:
        return devices

    safe = {}
    for name, cfg in devices.items():
        public = dict(cfg)
        if public.get("local_key"):
            public["local_key"] = "***"
            public["has_local_key"] = True
        else:
            public["has_local_key"] = False
        safe[name] = public
    return safe


def get_device(device_name: str):
    devices = load_devices()
    return devices.get(device_name)


def normalize_device_name(label: str, fallback: str = "tuya_light") -> str:
    value = (label or fallback).strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def upsert_device(device_name: str, device_config: dict):
    devices = load_devices()
    devices[device_name] = device_config
    save_devices(devices)
    return devices[device_name]
