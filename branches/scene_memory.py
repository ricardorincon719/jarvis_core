import json
import os
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from branches.music_memory import infer_genre


BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = Path(os.getenv("JARVIS_SCENE_MEMORY_DIR", str(BASE_DIR / "scene_memory")))
EVENTS_FILE = MEMORY_DIR / "compound_events.json"
SCENES_FILE = MEMORY_DIR / "learned_scenes.json"

DEFAULT_MIN_REPETITIONS = int(os.getenv("JARVIS_SCENE_MEMORY_MIN_REPETITIONS", "4"))
DEFAULT_MIN_UNIQUE_DAYS = int(os.getenv("JARVIS_SCENE_MEMORY_MIN_UNIQUE_DAYS", "2"))
MIN_EVENT_DATE = os.getenv("JARVIS_SCENE_MEMORY_MIN_DATE", "").strip()

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp_path, path)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, type(default)) else default
    except (json.JSONDecodeError, OSError):
        return default


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    value = str(value).strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value or "unknown"


def _parse_time(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _min_event_datetime() -> Optional[datetime]:
    if not MIN_EVENT_DATE:
        return None
    try:
        return datetime.fromisoformat(MIN_EVENT_DATE.replace("Z", "+00:00"))
    except ValueError:
        return None


def _time_window(dt: datetime) -> str:
    hour = dt.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _brightness_bucket(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if number <= 250:
        return "low"
    if number <= 700:
        return "medium"
    return "high"


def _scene_signature(event: Dict) -> Tuple[str, str, str, str, str, str, str]:
    music = event.get("music") or {}
    lights = event.get("lights") or {}
    light_scene = lights.get("scene") or {}
    dt = _parse_time(event.get("timestamp"))
    genre_or_query = music.get("genre") or music.get("query")

    return (
        _normalize_text(music.get("target")),
        _normalize_text(genre_or_query),
        _normalize_text(lights.get("device")),
        _normalize_text(lights.get("scene_name")),
        _normalize_text(light_scene.get("mode")),
        _brightness_bucket(light_scene.get("brightness")),
        _time_window(dt),
    )


def _scene_family_signature(event: Dict) -> Tuple[str, str, str, str]:
    music = event.get("music") or {}
    lights = event.get("lights") or {}
    light_scene = lights.get("scene") or {}
    genre_or_query = music.get("genre") or music.get("query")

    return (
        _normalize_text(genre_or_query),
        _normalize_text(lights.get("scene_name")),
        _normalize_text(light_scene.get("mode")),
        _brightness_bucket(light_scene.get("brightness")),
    )


def _stored_signature(scene: Dict) -> Optional[Tuple[str, ...]]:
    signature = scene.get("signature")
    if isinstance(signature, list):
        return tuple(signature)
    return None


def _build_scene_from_group(signature: Tuple[str, ...], events: List[Dict]) -> Dict:
    latest = max(events, key=lambda item: item.get("timestamp", ""))
    latest_music = latest.get("music") or {}
    latest_lights = latest.get("lights") or {}
    latest_light_scene = latest_lights.get("scene") or {}
    scene_id = "scene_" + uuid.uuid4().hex[:12]
    music_target = _normalize_text(latest_music.get("target"))
    music_key = _normalize_text(latest_music.get("genre") or latest_music.get("query"))
    light_device = _normalize_text(latest_lights.get("device"))
    scene_name = _normalize_text(latest_lights.get("scene_name"))
    light_mode = _normalize_text(latest_light_scene.get("mode"))
    brightness_bucket = _brightness_bucket(latest_light_scene.get("brightness"))
    time_window = _time_window(_parse_time(latest.get("timestamp")))

    return {
        "id": scene_id,
        "name": f"{music_key} + luz {scene_name} en {time_window}",
        "status": "candidate",
        "confidence": min(0.95, round(0.45 + (len(events) * 0.07), 2)),
        "evidence_count": len(events),
        "unique_days": len({_parse_time(item.get("timestamp")).date().isoformat() for item in events}),
        "first_seen": min(item.get("timestamp", "") for item in events),
        "last_seen": latest.get("timestamp"),
        "signature": list(signature),
        "trigger": {
            "intent": "compound_scene",
            "time_window": time_window,
            "requires_confirmation": True,
        },
        "actions": [
            {
                "domain": "music",
                "plugin": latest_music.get("plugin"),
                "type": "play",
                "target": music_target,
                "query": latest_music.get("query"),
                "genre": latest_music.get("genre"),
            },
            {
                "domain": "domotica",
                "plugin": latest_lights.get("plugin"),
                "type": "apply_scene",
                "device": light_device,
                "scene_name": scene_name,
                "scene": latest_lights.get("scene") or {},
            },
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
            "light_mode": light_mode,
            "brightness_bucket": brightness_bucket,
            "source": "jarvis_core.compound_dispatch",
        },
    }


def _extract_music_step(step: Dict) -> Optional[Dict]:
    plugin = step.get("plugin")
    if plugin not in {"music", "music_local"}:
        return None

    plan = ((step.get("debug") or {}).get("plan") or {})
    for action in plan.get("actions") or []:
        if action.get("type") == "play":
            query = action.get("query")
            return {
                "plugin": plugin,
                "target": plan.get("target") or ("laptop" if plugin == "music" else "cellphone"),
                "action": "play",
                "query": query,
                "genre": infer_genre(query),
                "prompt": step.get("compound_prompt"),
                "response": step.get("respuesta"),
            }
    return None


def _extract_light_step(step: Dict) -> Optional[Dict]:
    if step.get("plugin") != "domotica":
        return None

    plan = ((step.get("debug") or {}).get("plan") or {})
    for action in plan.get("actions") or []:
        if action.get("type") == "apply_scene":
            return {
                "plugin": "domotica",
                "device": action.get("device"),
                "action": "apply_scene",
                "scene_name": action.get("scene_name"),
                "scene": action.get("scene") or {},
                "prompt": step.get("compound_prompt"),
                "response": step.get("respuesta"),
            }
    return None


class SharedSceneMemory:
    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        for path in (EVENTS_FILE, SCENES_FILE):
            if not path.exists():
                _write_json(path, [])

    def record_compound_result(self, original_prompt: str, dispatch: List[Dict], result: Dict) -> Dict:
        if not result.get("ok"):
            return {"recorded": False, "reason": "compound_not_ok"}

        music_step = None
        light_step = None
        for step in result.get("steps") or []:
            music_step = music_step or _extract_music_step(step)
            light_step = light_step or _extract_light_step(step)

        if not music_step or not light_step:
            return {"recorded": False, "reason": "missing_music_or_light"}

        event = {
            "id": "compound_event_" + uuid.uuid4().hex[:12],
            "timestamp": _now_iso(),
            "prompt": original_prompt,
            "dispatch": dispatch,
            "music": music_step,
            "lights": light_step,
            "source": "jarvis_core.compound_dispatch",
        }

        with _lock:
            events = _read_json(EVENTS_FILE, [])
            events.append(event)
            _write_json(EVENTS_FILE, events[-1000:])
            candidates = self._detect_candidates_locked(events)

        return {
            "recorded": True,
            "event": event,
            "candidates_created": candidates,
        }

    def list_events(self, limit: int = 50) -> List[Dict]:
        with _lock:
            events = _read_json(EVENTS_FILE, [])
        return events[-limit:]

    def list_scenes(self, status: Optional[str] = None) -> List[Dict]:
        with _lock:
            scenes = _read_json(SCENES_FILE, [])
        if status:
            return [scene for scene in scenes if scene.get("status") == status]
        return scenes

    def update_scene_status(self, scene_id: str, status: str) -> Optional[Dict]:
        if status not in {"candidate", "approved", "rejected", "archived"}:
            raise ValueError("Estado de escena invalido")

        with _lock:
            scenes = _read_json(SCENES_FILE, [])
            for scene in scenes:
                if scene.get("id") == scene_id:
                    scene["status"] = status
                    scene["updated_at"] = _now_iso()
                    if status == "approved":
                        scene["last_confirmed_at"] = _now_iso()
                    _write_json(SCENES_FILE, scenes)
                    return scene
        return None

    def suggest_scene(self, context: Optional[Dict] = None) -> Optional[Dict]:
        context = context or {}
        now = _parse_time(context.get("timestamp"))
        current_window = _time_window(now)
        scenes = [
            scene for scene in self.list_scenes()
            if scene.get("status") in {"candidate", "approved"}
        ]

        scored = []
        for scene in scenes:
            trigger = scene.get("trigger") or {}
            score = float(scene.get("confidence") or 0)
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
            "suggestion": f"Detecte el patron '{scene.get('name')}'. Requiere confirmacion antes de activarse.",
        }

    def summary(self) -> Dict:
        with _lock:
            events = _read_json(EVENTS_FILE, [])
            scenes = _read_json(SCENES_FILE, [])
        return {
            "compound_events": len(events),
            "candidate_scenes": len([scene for scene in scenes if scene.get("status") == "candidate"]),
            "approved_scenes": len([scene for scene in scenes if scene.get("status") == "approved"]),
            "recent_events": events[-5:],
        }

    def _detect_candidates_locked(self, events: List[Dict]) -> List[Dict]:
        scenes = _read_json(SCENES_FILE, [])
        existing = {
            signature
            for signature in (_stored_signature(scene) for scene in scenes)
            if signature
        }
        min_dt = _min_event_datetime()

        grouped = defaultdict(list)
        for event in events:
            if min_dt and _parse_time(event.get("timestamp")) < min_dt:
                continue
            signature = _scene_signature(event)
            if "unknown" in signature[:5]:
                continue
            grouped[signature].append(event)

            family_signature = ("family",) + _scene_family_signature(event)
            if "unknown" not in family_signature[1:4]:
                grouped[family_signature].append(event)

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
            _write_json(SCENES_FILE, scenes)

        return created
