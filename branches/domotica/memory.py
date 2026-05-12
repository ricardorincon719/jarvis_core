import json
import os
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = Path(os.getenv("JARVIS_DOMOTICA_MEMORY_DIR", str(BASE_DIR / "memory")))
INTERACTIONS_FILE = MEMORY_DIR / "interactions.json"
LIGHT_EVENTS_FILE = MEMORY_DIR / "light_events.json"
LEARNED_SCENES_FILE = MEMORY_DIR / "learned_scenes.json"
PROFILE_FILE = MEMORY_DIR / "profile.json"
LAST_BEFORE_OFF_FILE = MEMORY_DIR / "last_before_off.json"

DEFAULT_MIN_REPETITIONS = 6
DEFAULT_MIN_UNIQUE_DAYS = 6

_lock = threading.Lock()


def _ensure_storage():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    for path in (INTERACTIONS_FILE, LIGHT_EVENTS_FILE, LEARNED_SCENES_FILE):
        if not path.exists():
            _write_json(path, [])
    if not PROFILE_FILE.exists():
        _write_json(PROFILE_FILE, {"notes": [], "updated_at": _now_iso()})


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, type(default)) else default
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp_path, path)


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _parse_time(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    value = str(value).strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value or "unknown"


def _time_window(dt: datetime) -> str:
    hour = dt.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _bucket(value, low: int, high: int) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if number <= low:
        return "low"
    if number <= high:
        return "medium"
    return "high"


def _scene_signature(event: Dict) -> Tuple[str, str, str, str, str, str, str]:
    scene = event.get("scene") or {}
    dt = _parse_time(event.get("timestamp"))
    return (
        _normalize_text(event.get("device")),
        _normalize_text(event.get("intent")),
        _normalize_text(event.get("scene_name")),
        _normalize_text(scene.get("mode")),
        _normalize_text(scene.get("color") or scene.get("raw_colour") or scene.get("rgb")),
        _bucket(scene.get("brightness"), 250, 700),
        _time_window(dt),
    )


def _stored_signature(scene: Dict) -> Optional[Tuple[str, ...]]:
    signature = scene.get("signature")
    if isinstance(signature, list):
        return tuple(signature)
    return None


def _build_scene_from_group(signature: Tuple[str, ...], events: List[Dict]) -> Dict:
    device, intent, scene_name, mode, color, brightness_bucket, time_window = signature
    latest_event = max(events, key=lambda item: item.get("timestamp", ""))
    scene = latest_event.get("scene") or {}
    scene_id = "domo_scene_" + uuid.uuid4().hex[:10]

    return {
        "id": scene_id,
        "name": f"{scene_name} en {time_window}",
        "status": "candidate",
        "confidence": min(0.95, round(0.45 + (len(events) * 0.07), 2)),
        "evidence_count": len(events),
        "unique_days": len({_parse_time(item.get("timestamp")).date().isoformat() for item in events}),
        "first_seen": min(item.get("timestamp", "") for item in events),
        "last_seen": latest_event.get("timestamp"),
        "signature": list(signature),
        "trigger": {
            "intent": intent,
            "time_window": time_window,
            "requires_confirmation": True,
        },
        "actions": [
            {
                "type": "apply_scene",
                "device": device,
                "scene_name": scene_name,
                "scene": scene,
            }
        ],
        "safety": {
            "requires_confirmation": True,
            "auto_execute": False,
        },
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "execution_count": 0,
        "last_confirmed_at": None,
        "metadata": {
            "mode": mode,
            "color": color,
            "brightness_bucket": brightness_bucket,
        },
    }


def detect_candidates_locked(events: Optional[List[Dict]] = None) -> List[Dict]:
    events = events if events is not None else _read_json(LIGHT_EVENTS_FILE, [])
    scenes = _read_json(LEARNED_SCENES_FILE, [])
    existing = {
        signature
        for signature in (_stored_signature(scene) for scene in scenes)
        if signature
    }

    grouped = defaultdict(list)
    for event in events:
        signature = _scene_signature(event)
        if "unknown" in signature[:4]:
            continue
        grouped[signature].append(event)

    created = []
    for signature, group in grouped.items():
        unique_days = {
            _parse_time(item.get("timestamp")).date().isoformat()
            for item in group
        }
        if len(group) < DEFAULT_MIN_REPETITIONS:
            continue
        if len(unique_days) < DEFAULT_MIN_UNIQUE_DAYS:
            continue
        if signature in existing:
            continue

        scene = _build_scene_from_group(signature, group)
        scenes.append(scene)
        existing.add(signature)
        created.append(scene)

    if created:
        _write_json(LEARNED_SCENES_FILE, scenes)

    return created


class DomoticaMemory:
    def __init__(self):
        _ensure_storage()

    def record_interaction(self, prompt: str, normalized: str, plan: Dict, response: Dict):
        item = {
            "id": "domo_interaction_" + uuid.uuid4().hex[:12],
            "timestamp": _now_iso(),
            "prompt": prompt,
            "normalized": normalized,
            "plan": plan,
            "response": response,
        }
        with _lock:
            interactions = _read_json(INTERACTIONS_FILE, [])
            interactions.append(item)
            _write_json(INTERACTIONS_FILE, interactions[-500:])
        return item

    def record_light_event(self, device: str, intent: str, scene_name: str, scene: Dict, result: Dict, prompt: str):
        event = {
            "id": "domo_event_" + uuid.uuid4().hex[:12],
            "timestamp": _now_iso(),
            "device": device,
            "intent": intent,
            "scene_name": scene_name,
            "scene": scene,
            "result": {
                "ok": bool(result.get("ok")),
                "classification": result.get("classification"),
                "ip": result.get("ip"),
            },
            "source": "jarvis_core.domotica_agent",
            "prompt": prompt,
        }
        with _lock:
            events = _read_json(LIGHT_EVENTS_FILE, [])
            events.append(event)
            _write_json(LIGHT_EVENTS_FILE, events[-1000:])
            candidates = detect_candidates_locked(events)
        return {"event": event, "candidates_created": candidates}

    def list_recent_interactions(self, limit: int = 8) -> List[Dict]:
        with _lock:
            interactions = _read_json(INTERACTIONS_FILE, [])
        return interactions[-limit:]

    def list_scenes(self, status: Optional[str] = None) -> List[Dict]:
        with _lock:
            scenes = _read_json(LEARNED_SCENES_FILE, [])
        if status:
            return [scene for scene in scenes if scene.get("status") == status]
        return scenes

    def find_scene(self, query: str, status: Optional[str] = None) -> Optional[Dict]:
        query = _normalize_text(query)
        candidates = self.list_scenes(status=status)
        for scene in candidates:
            if query in _normalize_text(scene.get("id")) or query in _normalize_text(scene.get("name")):
                return scene
        return None

    def update_scene_status(self, scene_id: str, status: str) -> Optional[Dict]:
        if status not in {"candidate", "approved", "rejected", "archived"}:
            raise ValueError("Estado de escena invalido")
        with _lock:
            scenes = _read_json(LEARNED_SCENES_FILE, [])
            for scene in scenes:
                if scene.get("id") == scene_id:
                    scene["status"] = status
                    scene["updated_at"] = _now_iso()
                    if status == "approved":
                        scene["last_confirmed_at"] = _now_iso()
                    _write_json(LEARNED_SCENES_FILE, scenes)
                    return scene
        return None

    def mark_scene_executed(self, scene_id: str):
        with _lock:
            scenes = _read_json(LEARNED_SCENES_FILE, [])
            for scene in scenes:
                if scene.get("id") == scene_id:
                    scene["execution_count"] = int(scene.get("execution_count") or 0) + 1
                    scene["last_executed_at"] = _now_iso()
                    scene["updated_at"] = _now_iso()
                    _write_json(LEARNED_SCENES_FILE, scenes)
                    return scene
        return None

    def suggest_scene(self, intent: Optional[str] = None) -> Optional[Dict]:
        now = datetime.now()
        current_window = _time_window(now)
        scored = []
        for scene in self.list_scenes():
            if scene.get("status") not in {"candidate", "approved"}:
                continue
            trigger = scene.get("trigger") or {}
            score = float(scene.get("confidence") or 0)
            if intent and trigger.get("intent") == _normalize_text(intent):
                score += 0.2
            if trigger.get("time_window") == current_window:
                score += 0.1
            scored.append((score, scene))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        scene = scored[0][1]
        return {
            "scene": scene,
            "requires_confirmation": True,
            "suggestion": f"Detecte el patron '{scene.get('name')}'. Dime 'activar escena {scene.get('id')}' si quieres aplicarlo.",
        }

    def save_last_before_off(self, scene: Dict):
        data = {
            "timestamp": _now_iso(),
            "scene": scene,
        }
        with _lock:
            _write_json(LAST_BEFORE_OFF_FILE, data)
        return data

    def load_last_before_off(self) -> Dict:
        with _lock:
            data = _read_json(LAST_BEFORE_OFF_FILE, {})
        scene = data.get("scene") if isinstance(data, dict) else None
        if not isinstance(scene, dict):
            raise ValueError("No hay estado previo guardado antes del apagado")
        restored = dict(scene)
        restored["switch"] = True
        return restored

    def remember_note(self, note: str, category: str = "general") -> Dict:
        item = {
            "id": "domo_note_" + uuid.uuid4().hex[:10],
            "timestamp": _now_iso(),
            "category": category,
            "note": note.strip(),
        }
        with _lock:
            profile = _read_json(PROFILE_FILE, {"notes": []})
            notes = profile.get("notes") if isinstance(profile.get("notes"), list) else []
            notes.append(item)
            profile["notes"] = notes[-100:]
            profile["updated_at"] = _now_iso()
            _write_json(PROFILE_FILE, profile)
        return item

    def summary(self) -> Dict:
        with _lock:
            interactions = _read_json(INTERACTIONS_FILE, [])
            events = _read_json(LIGHT_EVENTS_FILE, [])
            scenes = _read_json(LEARNED_SCENES_FILE, [])
            profile = _read_json(PROFILE_FILE, {"notes": []})
        return {
            "interactions": len(interactions),
            "light_events": len(events),
            "candidate_scenes": len([scene for scene in scenes if scene.get("status") == "candidate"]),
            "approved_scenes": len([scene for scene in scenes if scene.get("status") == "approved"]),
            "recent": interactions[-5:],
            "notes": profile.get("notes", [])[-5:],
        }
