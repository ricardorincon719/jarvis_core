import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    value = str(value).strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value or "unknown"


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


class MusicMemory:
    def __init__(self, storage_dir: Path, source: str, target: str):
        self.storage_dir = Path(storage_dir)
        self.source = source
        self.target = target
        self.interactions_file = self.storage_dir / "interactions.json"
        self.events_file = self.storage_dir / "music_events.json"
        self.profile_file = self.storage_dir / "profile.json"
        self.state_file = self.storage_dir / "agent_state.json"
        self._ensure_storage()

    def _ensure_storage(self):
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.interactions_file, self.events_file):
            if not path.exists():
                _write_json(path, [])
        if not self.profile_file.exists():
            _write_json(self.profile_file, {"notes": [], "updated_at": _now_iso()})
        if not self.state_file.exists():
            _write_json(self.state_file, {"updated_at": _now_iso()})

    def record_interaction(self, prompt: str, normalized: str, plan: Dict, response: Dict):
        item = {
            "id": "music_interaction_" + uuid.uuid4().hex[:12],
            "timestamp": _now_iso(),
            "source": self.source,
            "target": self.target,
            "prompt": prompt,
            "normalized": normalized,
            "plan": plan,
            "response": response,
        }
        with _lock:
            items = _read_json(self.interactions_file, [])
            items.append(item)
            _write_json(self.interactions_file, items[-500:])
        return item

    def record_music_event(self, action: str, query: Optional[str], result: Dict, prompt: str, metadata: Optional[Dict] = None):
        event = {
            "id": "music_event_" + uuid.uuid4().hex[:12],
            "timestamp": _now_iso(),
            "source": self.source,
            "target": self.target,
            "action": action,
            "query": query,
            "genre": infer_genre(query),
            "result": {
                "ok": not bool(result.get("error")),
                "message": result.get("message") or result.get("respuesta"),
            },
            "prompt": prompt,
            "metadata": metadata if isinstance(metadata, dict) else {},
        }
        with _lock:
            events = _read_json(self.events_file, [])
            events.append(event)
            _write_json(self.events_file, events[-1000:])
            state = _read_json(self.state_file, {})
            if action == "play":
                state["last_query"] = query
                state["last_genre"] = event["genre"]
                state["last_target"] = self.target
            state["last_action"] = action
            state["updated_at"] = _now_iso()
            _write_json(self.state_file, state)
        return event

    def remember_note(self, note: str, category: str = "general") -> Dict:
        item = {
            "id": "music_note_" + uuid.uuid4().hex[:10],
            "timestamp": _now_iso(),
            "source": self.source,
            "target": self.target,
            "category": category,
            "note": note.strip(),
        }
        with _lock:
            profile = _read_json(self.profile_file, {"notes": []})
            notes = profile.get("notes") if isinstance(profile.get("notes"), list) else []
            notes.append(item)
            profile["notes"] = notes[-100:]
            profile["updated_at"] = _now_iso()
            _write_json(self.profile_file, profile)
        return item

    def load_state(self) -> Dict:
        with _lock:
            return _read_json(self.state_file, {})

    def recent_events(self, limit: int = 10) -> List[Dict]:
        with _lock:
            events = _read_json(self.events_file, [])
        return events[-limit:]

    def summary(self) -> Dict:
        with _lock:
            interactions = _read_json(self.interactions_file, [])
            events = _read_json(self.events_file, [])
            profile = _read_json(self.profile_file, {"notes": []})
            state = _read_json(self.state_file, {})
        return {
            "source": self.source,
            "target": self.target,
            "interactions": len(interactions),
            "music_events": len(events),
            "last_query": state.get("last_query"),
            "last_genre": state.get("last_genre"),
            "last_action": state.get("last_action"),
            "recent_events": events[-5:],
            "notes": profile.get("notes", [])[-5:],
        }


def infer_genre(query: Optional[str]) -> str:
    text = _normalize_text(query)
    genre_words = [
        "jazz", "lofi", "rock", "salsa", "bachata", "reggaeton", "clasica",
        "clásica", "ambient", "relax", "synthwave", "metal", "pop", "blues",
        "piano", "instrumental",
    ]
    for word in genre_words:
        if word in text:
            return _normalize_text(word)
    return "unknown"
