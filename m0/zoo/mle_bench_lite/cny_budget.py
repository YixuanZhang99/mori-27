"""Durable admission for one serial, explicitly authorized DeepSeek campaign.

Amounts are frozen peak-price upper bounds, not supplier invoices. SQLite
transactions protect check/reserve against concurrent callers and crashes.
The hash chain/head detect damaged records, not malicious rollback by the owner.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid


POLICY = {"schema_version": 1, "currency": "CNY", "unit": "micro_cny",
          "provider_base_url": "https://api.deepseek.com", "model": "deepseek-flash",
          "input_micro_cny_per_token": 2, "output_micro_cny_per_token": 8,
          "context_tokens": 1048576, "max_output_tokens": 393216,
          "price_source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
          "price_verified_date": "2026-11-04", "cache_discount_applied": False,
          "invoice_verified": False, "concurrency": "one_unresolved_operation"}
ZERO_HASH = "0" * 64


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("expected SHA-256 identity")
    return value


def usage_run_id(usage_dir):
    """Stable trusted run locator, including when every local sidecar is lost."""
    return hashlib.sha256(str(Path(usage_dir).resolve()).encode()).hexdigest()


def validate_detailed_usage(value):
    """Require physical input/output counts; preserve only validated details."""
    if not isinstance(value, dict):
        raise ValueError("complete provider usage is required for CNY settlement")
    result = {key: _integer(value.get(key), key) for key in
              ("prompt_tokens", "completion_tokens", "total_tokens")}
    prompt, completion = result["prompt_tokens"], result["completion_tokens"]
    if prompt + completion != result["total_tokens"]:
        raise ValueError("provider usage totals disagree")
    for key in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        if key in value:
            result[key] = _integer(value[key], key)
            if result[key] > prompt:
                raise ValueError("cache detail exceeds prompt usage")
    hit, miss = result.get("prompt_cache_hit_tokens"), result.get("prompt_cache_miss_tokens")
    if hit is not None and miss is not None and hit + miss != prompt:
        raise ValueError("cache usage totals disagree")
    for key, field, bound in (("prompt_tokens_details", "cached_tokens", prompt),
                              ("completion_tokens_details", "reasoning_tokens", completion)):
        if key in value:
            details = value[key]
            if not isinstance(details, dict):
                raise ValueError("provider usage details must be objects")
            if field in details:
                count = _integer(details[field], field)
                if count > bound:
                    raise ValueError("provider usage detail exceeds its total")
                result[key] = {field: count}
                if field == "cached_tokens" and ((hit is not None and hit != count)
                        or (miss is not None and miss + count != prompt)):
                    raise ValueError("cache usage aliases disagree")
    return result


class CampaignBudget:
    """Open an existing ledger. Only explicit create() grants a fresh budget."""

    def __init__(self, path):
        self.path = Path(path).absolute()
        self._binding = None
        with self._transaction() as (_, policy, _state):
            self._binding = policy

    @classmethod
    def create(cls, path, *, limit_micro_cny=200000000):
        _integer(limit_micro_cny, "campaign limit", 1)
        if limit_micro_cny > 200000000:
            raise ValueError("campaign limit exceeds the supported CNY 200 authorization")
        path = Path(path).absolute()
        # Do not create missing parents or overwrite a partial previous setup.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        policy = {**POLICY, "campaign_id": uuid.uuid4().hex, "limit_micro_cny": limit_micro_cny}
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE policy (payload TEXT NOT NULL)")
            db.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL)")
            db.execute("CREATE TABLE head (seq INTEGER NOT NULL, hash TEXT NOT NULL)")
            db.execute("INSERT INTO policy VALUES (?)", (_json(policy),))
            db.execute("INSERT INTO head VALUES (0, ?)", (ZERO_HASH,))
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return cls(path)

    @contextmanager
    def _transaction(self):
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("existing regular campaign ledger is required")
        if stat.S_IMODE(self.path.stat().st_mode) != 0o600:
            raise ValueError("campaign ledger must have private 0600 permissions")
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                                 isolation_level=None, timeout=30)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            policy, state = self._read(db)
            if self._binding is not None and policy != self._binding:
                raise ValueError("campaign identity or policy changed")
            yield db, policy, state
            db.execute("COMMIT")
        except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError(f"campaign ledger integrity failed ({type(error).__name__})") from None
        finally:
            if db is not None:
                db.close()  # an unfinished transaction rolls back

    @staticmethod
    def _read(db):
        policies = db.execute("SELECT payload FROM policy").fetchall()
        if len(policies) != 1:
            raise ValueError("campaign policy is missing or duplicated")
        policy = json.loads(policies[0][0])
        if (not isinstance(policy, dict) or set(policy) != set(POLICY) | {"campaign_id", "limit_micro_cny"}
                or any(policy[key] != value for key, value in POLICY.items())
                or not isinstance(policy["campaign_id"], str)
                or re.fullmatch(r"[a-f0-9]{32}", policy["campaign_id"]) is None):
            raise ValueError("campaign policy is unsupported or damaged")
        limit = _integer(policy["limit_micro_cny"], "campaign limit", 1)
        if limit > 200000000:
            raise ValueError("campaign authorization exceeds supported limit")
        operations, pending, spent = {}, None, 0
        seq, previous = 0, ZERO_HASH
        for number, payload, recorded_hash in db.execute("SELECT seq, payload, hash FROM events ORDER BY seq"):
            event = json.loads(payload)
            if number != seq + 1 or recorded_hash != _hash({"seq": number, "previous": previous, "event": event}):
                raise ValueError("campaign journal hash chain is damaged")
            call_id = event.get("call_id")
            if not isinstance(call_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id) is None:
                raise ValueError("campaign call identity is invalid")
            if event.get("kind") == "reserve":
                if set(event) != {"kind", "call_id", "run_id", "request_sha256", "output_allowance", "reserved_micro_cny"}:
                    raise ValueError("campaign reservation shape is invalid")
                if event["run_id"] is not None:
                    _sha(event["run_id"])
                allowance = _integer(event["output_allowance"], "output allowance", 1)
                reserve = policy["context_tokens"] * 2 + allowance * 8
                if (allowance > policy["max_output_tokens"] or event["reserved_micro_cny"] != reserve
                        or pending is not None or call_id in operations or spent + reserve > limit):
                    raise ValueError("campaign reservation violates admission policy")
                _sha(event["request_sha256"])
                operations[call_id] = dict(event)
                pending = call_id
            elif event.get("kind") == "settle":
                if set(event) != {"kind", "call_id", "usage", "response_sha256", "upper_bound_micro_cny"} or pending != call_id:
                    raise ValueError("campaign settlement lacks its reservation")
                usage = validate_detailed_usage(event["usage"])
                reserve = operations[call_id]
                cost = usage["prompt_tokens"] * 2 + usage["completion_tokens"] * 8
                if (usage != event["usage"] or usage["prompt_tokens"] > policy["context_tokens"]
                        or usage["completion_tokens"] > reserve["output_allowance"]
                        or cost != event["upper_bound_micro_cny"] or cost > reserve["reserved_micro_cny"]):
                    raise ValueError("provider usage exceeds frozen reservation policy")
                _sha(event["response_sha256"])
                operations[call_id].update({key: value for key, value in event.items() if key != "kind"})
                spent += cost
                pending = None
            else:
                raise ValueError("unknown campaign event")
            seq, previous = number, recorded_hash
        if db.execute("SELECT seq, hash FROM head").fetchall() != [(seq, previous)]:
            raise ValueError("campaign journal head differs from recorded history")
        reserved = operations[pending]["reserved_micro_cny"] if pending else 0
        return policy, {"seq": seq, "hash": previous, "operations": operations,
                        "pending": pending, "spent": spent, "reserved": reserved}

    @staticmethod
    def _append(db, state, event):
        seq = state["seq"] + 1
        hashed = _hash({"seq": seq, "previous": state["hash"], "event": event})
        db.execute("INSERT INTO events VALUES (?, ?, ?)", (seq, _json(event), hashed))
        db.execute("UPDATE head SET seq=?, hash=?", (seq, hashed))
        # Validate the complete resulting journal before its transaction commits.
        CampaignBudget._read(db)

    def manifest_binding(self):
        with self._transaction() as (_, policy, _state):
            return {**policy, "policy_sha256": _hash(policy)}

    def reserve(self, call_id, request_sha256, output_allowance, *, run_id=None):
        _sha(request_sha256)
        _integer(output_allowance, "output allowance", 1)
        with self._transaction() as (db, policy, state):
            if state["pending"] is not None:
                raise ValueError("campaign has unresolved provider usage; no new paid request allowed")
            amount = policy["context_tokens"] * 2 + output_allowance * 8
            if state["spent"] + amount > policy["limit_micro_cny"]:
                raise ValueError("campaign CNY budget exhausted before provider invocation")
            self._append(db, state, {"kind": "reserve", "call_id": call_id,
                "run_id": run_id,
                "request_sha256": request_sha256, "output_allowance": output_allowance,
                "reserved_micro_cny": amount})

    def settle(self, call_id, usage, response_sha256):
        usage = validate_detailed_usage(usage)
        _sha(response_sha256)
        cost = usage["prompt_tokens"] * 2 + usage["completion_tokens"] * 8
        with self._transaction() as (db, _policy, state):
            old = state["operations"].get(call_id)
            if old is not None and "usage" in old:
                if old["usage"] == usage and old["response_sha256"] == response_sha256:
                    return
                raise ValueError("settled campaign operation cannot be changed")
            self._append(db, state, {"kind": "settle", "call_id": call_id,
                "usage": usage, "response_sha256": response_sha256, "upper_bound_micro_cny": cost})

    def snapshot(self):
        with self._transaction() as (_, policy, state):
            return {"campaign_id": policy["campaign_id"], "policy_sha256": _hash(policy),
                    "limit_micro_cny": policy["limit_micro_cny"], "invoice_verified": False,
                    "settled_upper_bound_micro_cny": state["spent"],
                    "reserved_micro_cny": state["reserved"],
                    "remaining_micro_cny": policy["limit_micro_cny"] - state["spent"] - state["reserved"],
                    "pending_calls": [state["pending"]] if state["pending"] else [],
                    "operations": list(state["operations"].values()),
                    "journal_head": {"seq": state["seq"], "sha256": state["hash"]}}
