import hashlib
import ipaddress
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from branches.domotica.config import list_devices, normalize_device_name, upsert_device
from branches.domotica.config import capabilities_for_type
from branches.domotica.tuya_cloud import build_cloud_client, cloud_configured

try:
    import tinytuya
except ModuleNotFoundError:
    tinytuya = None


BASE_DIR = Path(__file__).resolve().parent
PENDING_FILE = BASE_DIR / "pending_devices.json"
DEFAULT_DISCOVERY_TIMEOUT = int(os.getenv("JARVIS_TUYA_DISCOVERY_TIMEOUT", "8"))


def _infer_candidate_type(candidate: Dict) -> str:
    text = " ".join(
        str(candidate.get(key) or "").lower()
        for key in ("name_hint", "category", "product_key")
    )
    if any(word in text for word in ("plug", "enchufe", "tomada")) or candidate.get("category") in {"cz", "pc"}:
        return "plug"
    return "light"


def _read_pending() -> List[Dict]:
    if not PENDING_FILE.exists():
        return []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_pending(items: List[Dict]):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PENDING_FILE.with_suffix(PENDING_FILE.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp_path, PENDING_FILE)


def _now() -> int:
    return int(time.time())


def _candidate_id(device_id: str, mac: str, ip: str) -> str:
    stable_id = device_id or mac or ip
    raw = f"tuya|{stable_id}".encode("utf-8")
    return "tuya_" + hashlib.sha1(raw).hexdigest()[:12]


def _is_local_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def _best_ip(current: str, incoming: str) -> str:
    current = str(current or "").strip()
    incoming = str(incoming or "").strip()
    if _is_local_ip(current):
        return current
    if _is_local_ip(incoming):
        return incoming
    return current or incoming


def _existing_indexes(devices: Dict) -> Dict[str, set]:
    ids = set()
    macs = set()
    for cfg in devices.values():
        if cfg.get("device_id"):
            ids.add(str(cfg["device_id"]).lower())
        if cfg.get("mac"):
            macs.add(str(cfg["mac"]).lower())
    return {"ids": ids, "macs": macs}


def _known_device_name(candidate: Dict, devices: Dict) -> Optional[str]:
    device_id = str(candidate.get("device_id") or "").lower()
    mac = str(candidate.get("mac") or "").lower()
    for name, cfg in devices.items():
        if device_id and str(cfg.get("device_id") or "").lower() == device_id:
            return name
        if mac and str(cfg.get("mac") or "").lower() == mac:
            return name
    return None


def _refresh_known_device(candidate: Dict, devices: Dict) -> bool:
    name = _known_device_name(candidate, devices)
    if not name:
        return False

    current = dict(devices.get(name) or {})
    updated = dict(current)
    updated["ip"] = _best_ip(current.get("ip"), candidate.get("ip"))

    for key in ("mac", "version", "product_key", "provider", "driver"):
        if candidate.get(key) not in ("", None):
            updated[key] = candidate[key]
    if candidate.get("local_key") and not updated.get("local_key"):
        updated["local_key"] = candidate["local_key"]
    if not updated.get("name"):
        updated["name"] = name

    if updated == current:
        return False

    upsert_device(name, updated)
    devices[name] = updated
    return True


def _merge_pending(candidate: Dict, pending: List[Dict]) -> Dict:
    for item in pending:
        if item.get("candidate_id") == candidate.get("candidate_id"):
            original_first_seen = item.get("first_seen")
            item.update(candidate)
            item["first_seen"] = original_first_seen or candidate.get("first_seen") or _now()
            item["last_seen"] = _now()
            return item
    candidate["first_seen"] = _now()
    candidate["last_seen"] = _now()
    pending.append(candidate)
    return candidate


def _candidate_from_scan(ip: str, info: Dict, indexes: Dict[str, set]) -> Optional[Dict]:
    if not isinstance(info, dict):
        return None

    device_id = str(info.get("gwId") or info.get("id") or "").strip()
    mac = str(info.get("mac") or "").strip().lower()
    if not device_id and not mac:
        return None

    known = device_id.lower() in indexes["ids"] or (mac and mac in indexes["macs"])
    return {
        "candidate_id": _candidate_id(device_id, mac, ip),
        "provider": "tuya",
        "driver": "tuya_light",
        "status": "known" if known else "pending",
        "approval_required": not known,
        "device_id": device_id,
        "ip": ip,
        "mac": mac,
        "version": info.get("version") or info.get("ver") or 3.3,
        "product_key": info.get("productKey") or info.get("product_key"),
        "name_hint": info.get("name") or info.get("product_name") or "Lámpara Tuya",
        "raw": info,
    }


def _candidate_from_cloud(info: Dict, indexes: Dict[str, set], fallback_ip: str = "") -> Optional[Dict]:
    if not isinstance(info, dict):
        return None

    device_id = str(info.get("id") or info.get("device_id") or "").strip()
    if not device_id:
        return None

    mac = str(info.get("mac") or "").strip().lower()
    cloud_ip = str(info.get("ip") or "").strip()
    ip = _best_ip(fallback_ip, cloud_ip)
    known = device_id.lower() in indexes["ids"] or (mac and mac in indexes["macs"])
    local_key = str(info.get("local_key") or "").strip()

    candidate = {
        "candidate_id": _candidate_id(device_id, mac, ip),
        "provider": "tuya",
        "driver": "tuya_light",
        "status": "known" if known else "pending",
        "approval_required": not known,
        "device_id": device_id,
        "ip": ip,
        "mac": mac,
        "version": info.get("version") or info.get("ver") or 3.3,
        "product_key": info.get("product_id") or info.get("product_key"),
        "name_hint": info.get("name") or info.get("product_name") or "Lámpara Tuya",
        "category": info.get("category"),
        "cloud_online": info.get("online"),
        "cloud_synced": True,
        "has_local_key": bool(local_key),
        "raw": {k: v for k, v in info.items() if k != "local_key"},
    }
    if local_key:
        candidate["local_key"] = local_key
    return candidate


def _public_candidate(candidate: Dict) -> Dict:
    public = dict(candidate)
    if public.get("local_key"):
        public["local_key"] = "***"
        public["has_local_key"] = True
    else:
        public["has_local_key"] = bool(public.get("has_local_key"))
    return public


def _public_candidates(candidates: List[Dict]) -> List[Dict]:
    return [_public_candidate(item) for item in candidates]


def _enrich_candidate_from_cloud(candidate: Dict, cloud, indexes: Dict[str, set]) -> Dict:
    if not cloud or not candidate.get("device_id"):
        return candidate
    try:
        details = cloud.get_device_details(candidate["device_id"])
    except Exception as exc:
        candidate["cloud_error"] = str(exc)
        return candidate
    cloud_candidate = _candidate_from_cloud(details or {}, indexes, fallback_ip=candidate.get("ip") or "")
    if not cloud_candidate:
        return candidate
    merged = dict(candidate)
    merged.update({k: v for k, v in cloud_candidate.items() if k != "ip" and v not in ("", None)})
    merged["ip"] = _best_ip(candidate.get("ip"), cloud_candidate.get("ip"))
    if cloud_candidate.get("local_key"):
        merged["local_key"] = cloud_candidate["local_key"]
        merged["has_local_key"] = True
    return merged


def _discover_lan(timeout: int, indexes: Dict[str, set], cloud=None) -> List[Dict]:
    if tinytuya is None:
        return []

    discovered = []
    scanned = tinytuya.deviceScan(False, timeout)
    if not isinstance(scanned, dict):
        scanned = {}

    for ip, info in scanned.items():
        candidate = _candidate_from_scan(str(ip), info, indexes)
        if not candidate:
            continue
        discovered.append(_enrich_candidate_from_cloud(candidate, cloud, indexes))
    return discovered


def _discover_cloud(indexes: Dict[str, set], cloud) -> List[Dict]:
    if not cloud:
        return []
    result = cloud.list_devices(page_size=100)
    devices = result.get("devices") if isinstance(result, dict) else None
    if not isinstance(devices, list):
        devices = []
    discovered = []
    for info in devices:
        candidate = _candidate_from_cloud(info, indexes)
        if candidate:
            discovered.append(candidate)
    return discovered


def _merge_key(candidate: Dict) -> str:
    if candidate.get("device_id"):
        return f"id:{str(candidate['device_id']).lower()}"
    if candidate.get("mac"):
        return f"mac:{str(candidate['mac']).lower()}"
    return f"candidate:{candidate.get('candidate_id')}"


def _merge_discovered(existing: List[Dict], incoming: List[Dict]) -> List[Dict]:
    merged = {_merge_key(item): item for item in existing if item.get("candidate_id")}
    for item in incoming:
        key = _merge_key(item)
        if not key:
            continue
        current = merged.get(key, {})
        combined = dict(current)
        combined.update({k: v for k, v in item.items() if k != "ip" and v not in ("", None)})
        combined["ip"] = _best_ip(current.get("ip"), item.get("ip"))
        if item.get("local_key"):
            combined["local_key"] = item["local_key"]
            combined["has_local_key"] = True
        merged[key] = combined
    return list(merged.values())


def discover_tuya_devices(timeout: Optional[int] = None) -> Dict:
    timeout = int(timeout or DEFAULT_DISCOVERY_TIMEOUT)
    devices = list_devices(include_secrets=True)
    indexes = _existing_indexes(devices)
    pending = _read_pending()
    cloud = build_cloud_client()
    cloud_error = None
    lan_error = None

    try:
        lan_discovered = _discover_lan(timeout, indexes, cloud=cloud)
    except Exception as exc:
        lan_error = str(exc)
        lan_discovered = []

    try:
        cloud_discovered = _discover_cloud(indexes, cloud)
    except Exception as exc:
        cloud_error = str(exc)
        cloud_discovered = []

    if tinytuya is None and not cloud:
        raise RuntimeError("tinytuya_not_installed_and_tuya_cloud_not_configured")

    discovered = _merge_discovered(lan_discovered, cloud_discovered)
    refreshed_known = 0

    for candidate in discovered:
        if candidate.get("status") == "pending":
            _merge_pending(candidate, pending)
        elif candidate.get("status") == "known":
            if _refresh_known_device(candidate, devices):
                refreshed_known += 1

    _write_pending(pending)
    pending_visible = [
        item for item in pending
        if item.get("status") in {"pending", "needs_local_key"}
    ]

    return {
        "ok": True,
        "provider": "tuya",
        "cloud_configured": cloud_configured(),
        "cloud_error": cloud_error,
        "lan_error": lan_error,
        "discovered": _public_candidates(discovered),
        "pending": _public_candidates(pending_visible),
        "summary": {
            "total": len(discovered),
            "new": len([item for item in discovered if item.get("status") == "pending"]),
            "known": len([item for item in discovered if item.get("status") == "known"]),
            "with_local_key": len([item for item in discovered if item.get("local_key")]),
            "cloud": len(cloud_discovered),
            "lan": len(lan_discovered),
            "refreshed_known": refreshed_known,
        },
    }


def list_pending_devices() -> List[Dict]:
    candidates = [
        item for item in _read_pending()
        if item.get("status") in {"pending", "needs_local_key"}
    ]
    return _public_candidates(candidates)


def approve_pending_device(candidate_id: str, local_key: str = "", name: str = "", room: str = "") -> Dict:
    pending = _read_pending()
    candidate = next((item for item in pending if item.get("candidate_id") == candidate_id), None)
    if not candidate:
        raise ValueError("candidate_not_found")

    local_key = (
        local_key
        or candidate.get("local_key")
        or os.getenv("JARVIS_TUYA_NEW_DEVICE_LOCAL_KEY", "")
    ).strip()
    if not local_key:
        candidate["status"] = "needs_local_key"
        candidate["last_seen"] = _now()
        _write_pending(pending)
        raise ValueError("local_key_required")

    label = name.strip() or candidate.get("name_hint") or "Lámpara Tuya"
    device_name = normalize_device_name(label, fallback=f"tuya_{candidate.get('device_id') or candidate_id}")
    room = room.strip() or "sin_asignar"
    label_type_hint = label.lower()
    device_type = "plug" if any(word in label_type_hint for word in ("plug", "enchufe", "tomada")) else _infer_candidate_type(candidate)
    driver = "tuya_plug" if device_type == "plug" else "tuya_light"

    cfg = {
        "name": device_name,
        "label": label,
        "room": room,
        "type": device_type,
        "driver": driver,
        "capabilities": capabilities_for_type(device_type, driver),
        "provider": "tuya",
        "device_id": candidate.get("device_id"),
        "local_key": local_key,
        "ip": candidate.get("ip"),
        "mac": candidate.get("mac"),
        "version": float(candidate.get("version") or 3.3),
        "product_key": candidate.get("product_key"),
        "enabled": True,
        "approved_at": _now(),
    }
    device = upsert_device(device_name, cfg)

    candidate["status"] = "approved"
    candidate["device_name"] = device_name
    candidate["approved_at"] = _now()
    _write_pending(pending)

    return {"device_name": device_name, "device": {**device, "local_key": "***", "has_local_key": True}}


def reject_pending_device(candidate_id: str) -> Dict:
    pending = _read_pending()
    candidate = next((item for item in pending if item.get("candidate_id") == candidate_id), None)
    if not candidate:
        raise ValueError("candidate_not_found")
    candidate["status"] = "rejected"
    candidate["rejected_at"] = _now()
    _write_pending(pending)
    return candidate
