import json
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent / "devices.json"


def load_devices():
    if not CONFIG_FILE.exists():
        return {}

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_device(device_name: str):
    devices = load_devices()
    return devices.get(device_name)
