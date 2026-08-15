"""Persistencia y ciclo de vida de acciones que requieren consentimiento humano."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid


class ProposalNotFound(ValueError):
    pass


class ProposalAccessDenied(PermissionError):
    pass


class ProposalStateError(ValueError):
    pass


def canonical_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def requester_key(requester: dict) -> str:
    return f"{requester.get('type') or 'unknown'}:{requester.get('id') or 'unknown'}"


class ActionProposalStore:
    def __init__(self, path, ttl_seconds=180, max_items=500, clock=None):
        self.path = Path(path)
        self.ttl_seconds = max(15, int(ttl_seconds))
        self.max_items = max(20, int(max_items))
        self.clock = clock or time.time
        self._lock = threading.RLock()

    def create(self, kind: str, plan: dict, summary: str, requester: dict) -> dict:
        if not isinstance(plan, dict):
            raise ValueError("proposal_plan_must_be_object")
        if not kind or not summary:
            raise ValueError("proposal_kind_and_summary_required")

        with self._lock:
            items = self._read()
            changed = self._expire(items)
            plan_copy = deepcopy(plan)
            plan_hash = canonical_hash(plan_copy)
            owner = requester_key(requester)

            for item in reversed(items):
                if (
                    item.get("status") == "pending"
                    and item.get("requester_key") == owner
                    and item.get("plan_hash") == plan_hash
                ):
                    if changed:
                        self._write(items)
                    return deepcopy(item)

            now = self.clock()
            for item in items:
                if item.get("status") != "pending" or item.get("requester_key") != owner:
                    continue
                item["status"] = "cancelled"
                item["decision"] = "cancel"
                item["cancel_reason"] = "superseded"
                item["decided_at"] = self._iso(now)
                item["completed_at"] = self._iso(now)

            proposal = {
                "id": "action_" + uuid.uuid4().hex[:16],
                "kind": kind,
                "status": "pending",
                "summary": str(summary).strip()[:500],
                "plan": plan_copy,
                "plan_hash": plan_hash,
                "requester": deepcopy(requester),
                "requester_key": owner,
                "created_at": self._iso(now),
                "expires_at": self._iso(now + self.ttl_seconds),
                "expires_at_epoch": now + self.ttl_seconds,
                "decision": None,
                "idempotency_key": None,
                "result": None,
            }
            items.append(proposal)
            self._write(items[-self.max_items:])
            return deepcopy(proposal)

    def list_pending(self, requester: dict, include_all_for_master=True) -> list:
        with self._lock:
            items = self._read()
            changed = self._expire(items)
            if changed:
                self._write(items)
            return [
                deepcopy(item)
                for item in items
                if item.get("status") == "pending"
                and (
                    self._can_access(item, requester)
                    if include_all_for_master
                    else item.get("requester_key") == requester_key(requester)
                )
            ]

    def claim(self, proposal_id: str, decision: str, idempotency_key: str, requester: dict):
        normalized = str(decision or "").strip().lower()
        if normalized in {"accept", "confirm", "confirmed", "approve"}:
            normalized = "accept"
        elif normalized in {"cancel", "reject", "deny"}:
            normalized = "cancel"
        else:
            raise ValueError("invalid_decision")

        idem = str(idempotency_key or "").strip()[:160]
        if not idem:
            raise ValueError("idempotency_key_required")

        with self._lock:
            items = self._read()
            expired_changed = self._expire(items)
            proposal = self._find(items, proposal_id)
            if not self._can_access(proposal, requester):
                if expired_changed:
                    self._write(items)
                raise ProposalAccessDenied("proposal_access_denied")
            if canonical_hash(proposal.get("plan")) != proposal.get("plan_hash"):
                if expired_changed:
                    self._write(items)
                raise ProposalStateError("proposal_integrity_error")

            if proposal.get("status") != "pending":
                if (
                    proposal.get("idempotency_key") == idem
                    and proposal.get("decision") == normalized
                ):
                    self._write(items)
                    return deepcopy(proposal), False
                if expired_changed:
                    self._write(items)
                raise ProposalStateError(f"proposal_{proposal.get('status') or 'unavailable'}")

            proposal["decision"] = normalized
            proposal["idempotency_key"] = idem
            proposal["decided_at"] = self._iso(self.clock())
            proposal["status"] = "executing" if normalized == "accept" else "cancelled"
            self._write(items)
            return deepcopy(proposal), True

    def complete(self, proposal_id: str, result: dict, success: bool) -> dict:
        with self._lock:
            items = self._read()
            proposal = self._find(items, proposal_id)
            if proposal.get("status") != "executing":
                raise ProposalStateError(f"proposal_{proposal.get('status') or 'unavailable'}")
            proposal["status"] = "executed" if success else "failed"
            proposal["completed_at"] = self._iso(self.clock())
            proposal["result"] = deepcopy(result)
            self._write(items)
            return deepcopy(proposal)

    @staticmethod
    def public(proposal: dict) -> dict:
        safe = deepcopy(proposal)
        safe.pop("requester", None)
        safe.pop("requester_key", None)
        safe.pop("expires_at_epoch", None)
        return safe

    def _find(self, items: list, proposal_id: str) -> dict:
        for item in items:
            if item.get("id") == proposal_id:
                return item
        raise ProposalNotFound("proposal_not_found")

    @staticmethod
    def _can_access(proposal: dict, requester: dict) -> bool:
        return requester.get("type") == "master" or proposal.get("requester_key") == requester_key(requester)

    def _expire(self, items: list) -> bool:
        now = self.clock()
        changed = False
        for item in items:
            if item.get("status") != "pending":
                continue
            if float(item.get("expires_at_epoch") or 0) <= now:
                item["status"] = "expired"
                item["completed_at"] = self._iso(now)
                changed = True
        return changed

    def _read(self) -> list:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
            return payload if isinstance(payload, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _write(self, items: list):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as file_handle:
                json.dump(items, file_handle, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _iso(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
