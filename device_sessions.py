import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional


SCHEMA_VERSION = 2


class DeviceSessionStore:
    def __init__(
        self,
        path: Path,
        ttl_seconds: int,
        max_sessions: int = 100,
        now_fn: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_sessions = max(1, int(max_sessions))
        self.now_fn = now_fn
        self._lock = threading.Lock()

    def issue(self, device_id: str = "", device_name: str = "", device_public_key: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = self.now_fn()
        session = {
            "device_id": self._clean(device_id, "unknown", 120),
            "device_name": self._clean(device_name, "PEARL Client", 120),
            "device_public_key": self._clean(device_public_key, "", 4096),
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }

        with self._lock:
            data = self._read()
            sessions = self._active_sessions(data.get("sessions") or {}, now)
            sessions[self._hash_token(token)] = session
            sessions = self._limit_sessions(sessions)
            self._write({"schema_version": SCHEMA_VERSION, "sessions": sessions})

        return token

    def validate(self, token: str) -> Optional[Dict]:
        if not token:
            return None

        now = self.now_fn()
        token_hash = self._hash_token(token)
        with self._lock:
            data = self._read()
            stored_sessions = data.get("sessions") or {}
            sessions = self._active_sessions(stored_sessions, now)
            if sessions != stored_sessions:
                self._write({"schema_version": SCHEMA_VERSION, "sessions": sessions})
            session = sessions.get(token_hash)
            return dict(session) if session else None

    def revoke(self, token: str) -> bool:
        if not token:
            return False

        with self._lock:
            data = self._read()
            sessions = data.get("sessions") or {}
            removed = sessions.pop(self._hash_token(token), None) is not None
            if removed:
                self._write({"schema_version": SCHEMA_VERSION, "sessions": sessions})
            return removed

    def prune(self) -> int:
        now = self.now_fn()
        with self._lock:
            data = self._read()
            stored_sessions = data.get("sessions") or {}
            sessions = self._active_sessions(stored_sessions, now)
            removed = len(stored_sessions) - len(sessions)
            if removed:
                self._write({"schema_version": SCHEMA_VERSION, "sessions": sessions})
            return removed

    def _read(self) -> Dict:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "sessions": {}}
        try:
            with self.path.open("r", encoding="utf-8") as file_handle:
                data = json.load(file_handle)
            if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
                return {"schema_version": SCHEMA_VERSION, "sessions": {}}
            return data
        except (json.JSONDecodeError, OSError):
            return {"schema_version": SCHEMA_VERSION, "sessions": {}}

    def _write(self, data: Dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as file_handle:
            json.dump(data, file_handle, ensure_ascii=False, indent=2)
            file_handle.write("\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.path)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean(value: str, default: str, max_length: int) -> str:
        clean_value = str(value or "").strip()
        return (clean_value or default)[:max_length]

    @staticmethod
    def _active_sessions(sessions: Dict, now: float) -> Dict:
        return {
            token_hash: session
            for token_hash, session in sessions.items()
            if isinstance(session, dict) and DeviceSessionStore._number(session.get("expires_at")) > now
        }

    def _limit_sessions(self, sessions: Dict) -> Dict:
        ordered = sorted(
            sessions.items(),
            key=lambda item: self._number(item[1].get("created_at")),
            reverse=True,
        )
        return dict(ordered[: self.max_sessions])

    @staticmethod
    def _number(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
