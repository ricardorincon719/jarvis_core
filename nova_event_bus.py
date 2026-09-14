"""Outbox durable y fail-open para observaciones enviadas a Nova."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests


class NovaEventBus:
    def __init__(
        self,
        database_path,
        nova_url: str,
        *,
        timeout_seconds: float = 5.0,
        retry_seconds: float = 15.0,
        http_post: Callable | None = None,
        start_worker: bool = True,
        max_attempts: int = 8,
        clock: Callable = time.time,
    ):
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            path = Path(self.database_path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.database_path = str(path)
        self.nova_url = nova_url.rstrip("/")
        self.timeout_seconds = max(0.2, float(timeout_seconds))
        self.retry_seconds = max(1.0, float(retry_seconds))
        self.http_post = http_post or requests.post
        self.max_attempts = max(1, int(max_attempts))
        self.clock = clock
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
            timeout=5.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._create_schema()
        self._worker = None
        if start_worker:
            self._wake.set()  # La cola existente se atiende al arrancar.
            self._worker = threading.Thread(
                target=self._run,
                name="pearl-nova-event-bus",
                daemon=True,
            )
            self._worker.start()

    def _create_schema(self):
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nova_event_outbox (
                    event_id TEXT PRIMARY KEY,
                    envelope_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            columns = {row[1] for row in self._connection.execute(
                "PRAGMA table_info(nova_event_outbox)")}
            for name, definition in (("discarded", "INTEGER NOT NULL DEFAULT 0"),
                                     ("next_attempt_at", "REAL NOT NULL DEFAULT 0")):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE nova_event_outbox ADD COLUMN {name} {definition}")
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS outbox_ready ON nova_event_outbox"
                "(status,discarded,next_attempt_at,created_at)")

    def publish_compound_response(self, prompt: str, response: dict) -> str | None:
        envelope = self.build_compound_event(prompt, response)
        if envelope is None:
            return None
        self.publish(envelope)
        return envelope["event_id"]

    @staticmethod
    def build_compound_event(prompt: str, response: dict) -> dict | None:
        if not isinstance(response, dict) or not response.get("compound"):
            return None
        scene_memory = response.get("scene_memory") or {}
        scene_event = scene_memory.get("event") if isinstance(scene_memory, dict) else None
        source_id = scene_event.get("id") if isinstance(scene_event, dict) else None
        event_id = source_id or "pearl_compound_" + uuid.uuid4().hex
        occurred_at = (
            scene_event.get("timestamp")
            if isinstance(scene_event, dict)
            else None
        ) or datetime.now(timezone.utc).isoformat()
        return {
            "event_id": str(event_id),
            "source": "pearl-core",
            "event_type": "pearl.compound.completed",
            "occurred_at": str(occurred_at),
            "correlation_id": str(event_id),
            "payload": {
                "prompt": str(prompt or ""),
                "ok": bool(response.get("ok", True)),
                "steps": response.get("steps") or [],
                "scene_event": scene_event or {},
            },
        }

    def publish(self, envelope: dict):
        event_id = str(envelope.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("event_id_required")
        encoded = json.dumps(
            envelope,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT envelope_json FROM nova_event_outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is not None and row["envelope_json"] != encoded:
                raise ValueError("event_id_conflict")
            self._connection.execute(
                """
                INSERT OR IGNORE INTO nova_event_outbox (
                    event_id, envelope_json, status, attempts, last_error,
                    created_at, updated_at
                ) VALUES (?, ?, 'pending', 0, NULL, ?, ?)
                """,
                (event_id, encoded, now, now),
            )
        self._wake.set()

    def deliver_pending_once(self) -> int:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_id, envelope_json, attempts
                FROM nova_event_outbox
                WHERE status = 'pending' AND discarded=0 AND next_attempt_at <= ?
                ORDER BY next_attempt_at, created_at, event_id
                LIMIT 100
                """, (self.clock(),)
            ).fetchall()
        delivered = 0
        for row in rows:
            if self._closed:
                break
            event_id = row["event_id"]
            error = None
            permanent = False
            try:
                response = self.http_post(
                    f"{self.nova_url}/v1/events",
                    json=json.loads(row["envelope_json"]),
                    timeout=(1.0, self.timeout_seconds),
                )
                if not 200 <= response.status_code < 300:
                    error = f"http_{response.status_code}"
                    permanent = response.status_code in {400, 401, 403, 404, 410, 422}
                    if response.status_code == 409:
                        permanent = response.json().get("error", {}).get("code") == "idempotency_conflict"
                else:
                    body = response.json()
                    output = body.get("output", {}) if isinstance(body, dict) else {}
                    candidate = output.get("complex_event", {}) if isinstance(output, dict) else {}
                    if (body.get("status") != "succeeded" or output.get("status") != "candidate"
                            or candidate.get("source_event_id") != event_id
                            or candidate.get("auto_execute") is not False):
                        error = "invalid_delivery_response"
            except Exception as exc:
                error = type(exc).__name__
            now = datetime.now(timezone.utc).isoformat()
            with self._lock, self._connection:
                if error is None:
                    self._connection.execute(
                        """
                        UPDATE nova_event_outbox
                        SET status = 'delivered', attempts = attempts + 1,
                            last_error = NULL, updated_at = ?
                        WHERE event_id = ? AND status = 'pending'
                        """,
                        (now, event_id),
                    )
                    delivered += 1
                else:
                    self._connection.execute(
                        """
                        UPDATE nova_event_outbox
                        SET attempts = attempts + 1, last_error = ?, updated_at = ?,
                            discarded = ?, next_attempt_at = ?
                        WHERE event_id = ? AND status = 'pending'
                        """,
                        (
                            error, now,
                            int(permanent or row["attempts"] + 1 >= self.max_attempts),
                            self.clock() + min(
                                300.0,
                                self.retry_seconds * 2 ** min(row["attempts"], 8),
                            ),
                            event_id,
                        ),
                    )
        return delivered

    def list_outbox(self) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_id, CASE WHEN discarded=1 THEN 'discarded' ELSE status END AS status,
                       attempts, last_error, next_attempt_at
                FROM nova_event_outbox
                ORDER BY created_at, event_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def health_summary(self) -> dict:
        """Resumen operativo sin preguntas, payloads ni identificadores de eventos."""
        now = datetime.now(timezone.utc)
        with self._lock:
            rows = self._connection.execute(
                "SELECT CASE WHEN discarded=1 THEN 'discarded' ELSE status END,COUNT(*) "
                "FROM nova_event_outbox GROUP BY 1"
            ).fetchall()
            pending = self._connection.execute(
                "SELECT MIN(created_at),MAX(updated_at),MAX(attempts) "
                "FROM nova_event_outbox WHERE status='pending' AND discarded=0"
            ).fetchone()
            last_attempt = self._connection.execute(
                "SELECT MAX(updated_at) FROM nova_event_outbox WHERE attempts>0"
            ).fetchone()[0]
        age = max(0, (now-datetime.fromisoformat(pending[0])).total_seconds()) if pending[0] else None
        return {"counts": dict(rows), "oldest_pending_age_seconds": age,
                "last_pending_update_at": pending[1], "last_attempt_at": last_attempt,
                "max_pending_attempts": pending[2] or 0,
                "worker_running": bool(self._worker and self._worker.is_alive()),
                "degraded": bool(dict(rows).get('discarded') or (age is not None and age >= 300))}

    def _run(self):
        while not self._closed:
            self._wake.wait(self.retry_seconds)
            self._wake.clear()
            if self._closed:
                return
            try:
                self.deliver_pending_once()
            except Exception:
                time.sleep(min(self.retry_seconds, 2.0))

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._wake.set()
        if self._worker is not None:
            self._worker.join()
        with self._lock:
            self._connection.close()
