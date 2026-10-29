"""Unified X2 human-in-the-loop control plane.

Approval is bound to (action, canonical payload hash), persisted append-only,
and consumed exactly once.  A paused controller denies both auto and review
actions until an explicit resume event is appended.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from core.hitl.types import ControlDecision, InteractionMode
from core.x1.store import AppendOnlyStore


def payload_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class HITLController:
    def __init__(self, store: AppendOnlyStore, mode: InteractionMode = "review"):
        if mode not in {"auto", "review"}:
            raise ValueError("phase-one HITL modes are auto and review")
        self.store = store
        self.mode = mode
        self.requests: dict[str, dict] = {}
        self.decisions: dict[str, dict] = {}
        self.consumed: set[str] = set()
        self.paused = False
        self._restore()

    def _restore(self) -> None:
        for record in self.store.read():
            kind, payload = record["kind"], record["payload"]
            if kind == "hitl_request":
                self.requests[payload["request_id"]] = {**payload, "status": "pending"}
            elif kind == "hitl_decision":
                self.decisions[payload["decision_id"]] = payload
                if payload["request_id"] in self.requests:
                    self.requests[payload["request_id"]]["status"] = payload["verdict"]
            elif kind == "hitl_consumed":
                self.consumed.add(payload["request_id"])
            elif kind == "hitl_pause":
                self.paused = True
            elif kind == "hitl_resume":
                self.paused = False

    def _reload(self) -> None:
        """Observe decisions appended by another reviewer/process."""
        self.requests.clear()
        self.decisions.clear()
        self.consumed.clear()
        self.paused = False
        self._restore()

    def _decision(self, request: dict, verdict: str, allowed: bool,
                  reason: str = "", decision_id: str | None = None) -> ControlDecision:
        return ControlDecision(request["request_id"], decision_id, request["action"],
                               request["payload_sha256"], self.mode, verdict, allowed, reason)

    def request(self, action: str, payload: Any) -> ControlDecision:
        if not action:
            raise ValueError("controlled action name is required")
        request_id = "hitl-" + uuid.uuid4().hex
        request = {"request_id": request_id, "action": action,
                   "payload_sha256": payload_digest(payload), "mode": self.mode}
        self.requests[request_id] = {**request, "status": "pending"}
        self.store.append("hitl_request", request)
        if self.mode == "auto":
            return self._append_decision(request, "approved", "system:auto", "automatic mode")
        return self._decision(request, "pending", False, "human approval required")

    def _append_decision(self, request: dict, verdict: str, actor: str,
                         reason: str) -> ControlDecision:
        decision_id = "decision-" + uuid.uuid4().hex
        payload = {"decision_id": decision_id, "request_id": request["request_id"],
                   "action": request["action"], "payload_sha256": request["payload_sha256"],
                   "verdict": verdict, "actor": actor, "reason": reason}
        self.store.append("hitl_decision", payload)
        self.decisions[decision_id] = payload
        request["status"] = verdict
        return self._decision(request, verdict, verdict == "approved", reason, decision_id)

    def approve(self, request_id: str, actor: str, reason: str = "") -> ControlDecision:
        return self._review_decision(request_id, "approved", actor, reason)

    def reject(self, request_id: str, actor: str, reason: str = "") -> ControlDecision:
        return self._review_decision(request_id, "rejected", actor, reason)

    def _review_decision(self, request_id: str, verdict: str,
                         actor: str, reason: str) -> ControlDecision:
        if self.mode != "review":
            raise ValueError("manual decisions require review mode")
        if not actor:
            raise ValueError("human decision actor is required")
        self._reload()
        request = self.requests.get(request_id)
        if request is None:
            raise ValueError("unknown HITL request")
        if request["status"] != "pending" or request_id in self.consumed:
            raise ValueError("HITL request is no longer pending")
        return self._append_decision(request, verdict, actor, reason)

    def authorize(self, action: str, payload: Any) -> ControlDecision:
        """Authorize one controlled action; an approval can authorize only once."""
        self._reload()
        digest = payload_digest(payload)
        if self.paused:
            request = {"request_id": "paused", "action": action, "payload_sha256": digest}
            return self._decision(request, "denied", False, "controller is paused")
        if self.mode == "auto":
            return self.request(action, payload)
        approved = [request for request in self.requests.values()
                    if request["action"] == action
                    and request["payload_sha256"] == digest
                    and request["status"] == "approved"
                    and request["request_id"] not in self.consumed]
        if approved:
            request = sorted(approved, key=lambda item: item["request_id"])[0]
            self.consumed.add(request["request_id"])
            self.store.append("hitl_consumed", {"request_id": request["request_id"],
                                                "action": action,
                                                "payload_sha256": digest})
            return self._decision(request, "approved", True, "approval consumed")
        pending = [request for request in self.requests.values()
                   if request["action"] == action
                   and request["payload_sha256"] == digest
                   and request["status"] == "pending"]
        if pending:
            return self._decision(pending[-1], "pending", False, "human approval required")
        return self.request(action, payload)

    def pending(self) -> list[dict]:
        self._reload()
        return [{key: value for key, value in request.items() if key != "status"}
                for request in self.requests.values() if request["status"] == "pending"]

    def pause(self, actor: str, reason: str) -> None:
        if not actor or not reason:
            raise ValueError("pause requires actor and reason")
        self._reload()
        self.store.append("hitl_pause", {"actor": actor, "reason": reason})
        self.paused = True

    def resume(self, actor: str, reason: str) -> None:
        if not actor or not reason:
            raise ValueError("resume requires actor and reason")
        self._reload()
        self.store.append("hitl_resume", {"actor": actor, "reason": reason})
        self.paused = False
