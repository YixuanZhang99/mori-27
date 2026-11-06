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


def _identifier(value, label):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
        raise ValueError(f"{label} must be a nonempty bounded identifier")
    return value


def _head_anchor(value):
    if type(value) is not dict or set(value) != {"seq", "sha256"}:
        raise ValueError("currency journal head anchor requires sequence and SHA-256")
    _integer(value["seq"], "currency journal head sequence")
    _sha(value["sha256"])
    return value


def _plan_ref(value):
    if type(value) is not str or not value.startswith("sha256:"):
        raise ValueError("control plan requires a SHA-256 reference")
    _sha(value[7:])
    return value


def _call_bound(policy, value):
    if type(value) is not dict or set(value) != {"schema_version", "output_allowance", "reserved_micro_cny"} \
            or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("currency bound requires the versioned output allowance and exact upper bound")
    allowance = _integer(value["output_allowance"], "output allowance", 1)
    amount = _integer(value["reserved_micro_cny"], "reserved currency", 1)
    if allowance > policy["max_output_tokens"] or amount != policy["context_tokens"] * 2 + allowance * 8:
        raise ValueError("currency bound differs from frozen full-context pricing policy")
    return dict(value)


def _obligations(policy, run_id, plan_ref, values):
    if type(values) is not list or not values:
        raise ValueError("control obligations must be a nonempty list")
    result, seen = [], set()
    for value in values:
        if type(value) is not dict or set(value) != {"slot_id", "phase", "ordinal", "bound"}:
            raise ValueError("control obligation requires frozen slot, phase, ordinal and bound")
        slot = _identifier(value["slot_id"], "control slot")
        phase = value["phase"]
        if phase not in {"operator", "evaluation"} or type(phase) is not str:
            raise ValueError("control obligation phase must be operator or evaluation")
        ordinal = _integer(value["ordinal"], "provider ordinal")
        identity = (slot, phase, ordinal)
        if identity in seen:
            raise ValueError("duplicate control currency obligation")
        seen.add(identity)
        result.append({"slot_id": slot, "phase": phase, "ordinal": ordinal,
                       "bound": _call_bound(policy, value["bound"])})
    return sorted(result, key=lambda item: (item["slot_id"], item["phase"], item["ordinal"]))


def _outstanding(governance):
    return sum(obligation["bound"]["reserved_micro_cny"]
               for run in governance["runs"].values() for obligation in run["obligations"]
               if obligation["status"] == "pending")


def _run(governance, run_id, plan_ref=None):
    _sha(run_id)
    if not governance["enabled"]:
        raise ValueError("explicit currency governance migration must enable protection first")
    run = governance["runs"].get(run_id)
    if run is None:
        raise ValueError("currency run has no protected control plan")
    if plan_ref is not None and run["plan_ref"] != _plan_ref(plan_ref):
        raise ValueError("currency run plan differs from frozen protection")
    return run


def _obligation(run, slot_id, phase, ordinal):
    for obligation in run["obligations"]:
        if (obligation["slot_id"], obligation["phase"], obligation["ordinal"]) == (slot_id, phase, ordinal):
            return obligation
    raise ValueError("call has no matching frozen control currency obligation")


def _reduce_governance(event, policy, governance, operations, pending, spent, *, seq, previous):
    """Reduce one version-two event; all monetary conversions stay in one transaction."""
    kind = event.get("kind")
    if type(event.get("schema_version")) is not int or event["schema_version"] != 2:
        raise ValueError("unsupported currency governance event version")
    if kind == "governance_enabled":
        if set(event) != {"kind", "schema_version", "previous_head", "policy_sha256"} \
                or governance["enabled"] or pending is not None \
                or _head_anchor(event["previous_head"]) != {"seq": seq, "sha256": previous} \
                or event["policy_sha256"] != _hash(policy):
            raise ValueError("currency governance migration anchor is invalid or has unresolved calls")
        governance["enabled"] = True
        return pending, spent
    if not governance["enabled"]:
        raise ValueError("currency governance events precede explicit migration")
    if kind == "freeze_circle_pilot":
        fields = {"kind", "schema_version", "plan_ref", "tree_ref", "wallclock_seconds"}
        if set(event) not in (fields, fields | {"require_runtime"}) or \
                ("require_runtime" in event and event["require_runtime"] is not True):
            raise ValueError("circle pilot binding has invalid fields")
        seconds = _integer(event["wallclock_seconds"], "cell duration", 1)
        if seconds > 86400:
            raise ValueError("cell duration exceeds the supported limit")
        value = {"plan_ref": _plan_ref(event["plan_ref"]), "tree_ref": _plan_ref(event["tree_ref"]),
                 "wallclock_seconds": seconds}
        if "require_runtime" in event:
            value['require_runtime'] = True
        if governance["circle_pilot"] is not None or governance["cell_claims"] or pending is not None:
            raise ValueError("circle pilot must freeze once before any cell or unresolved call")
        governance["circle_pilot"] = value
    elif kind == "freeze_circle_runtime":
        if set(event) != {"kind", "schema_version", "plan_ref", "tree_ref", "runtime_ref", "python_sha256"}:
            raise ValueError("circle runtime binding has invalid fields")
        value = {"plan_ref": _plan_ref(event["plan_ref"]), "tree_ref": _plan_ref(event["tree_ref"]),
                 "runtime_ref": _plan_ref(event["runtime_ref"]), "python_sha256": _sha(event["python_sha256"])}
        pilot = governance["circle_pilot"]
        if pilot is None or pilot["plan_ref"] != value["plan_ref"] or pilot["tree_ref"] != value["tree_ref"] or \
                governance["circle_runtime"] is not None or governance["cell_claims"] or pending is not None:
            raise ValueError("circle runtime must freeze once before any cell or unresolved call")
        governance["circle_runtime"] = value
    elif kind == "claim_cell_deadline":
        fields = {"kind", "schema_version", "cell_id", "plan_ref", "record_sha256"}
        pilot = governance["circle_pilot"]
        if set(event) != (fields | {"seconds"} if pilot is not None else fields):
            raise ValueError("cell deadline claim has invalid fields")
        cell_id = _identifier(event["cell_id"], "cell identity")
        plan_ref = _plan_ref(event["plan_ref"])
        digest = _sha(event["record_sha256"])
        if pilot is not None:
            if pilot.get('require_runtime') and governance['circle_runtime'] is None:
                raise ValueError("cell requires the frozen runtime")
            if pilot["plan_ref"] != plan_ref:
                raise ValueError("cell deadline differs from the frozen pilot plan")
            if re.fullmatch(r'(?:vendor|mori)-[012]', cell_id) is None:
                raise ValueError("cell identity is outside the frozen pilot")
            if type(event["seconds"]) is not int or event["seconds"] != pilot["wallclock_seconds"]:
                raise ValueError("cell duration differs from the frozen pilot")
        if cell_id in governance["cell_claims"]:
            raise ValueError("cell deadline claim already exists")
        governance["cell_claims"][cell_id] = {"plan_ref": plan_ref, "record_sha256": digest,
                                               "observation_sequence": 0, "observation_sha256": digest}
    elif kind == "observe_cell_deadline":
        if set(event) != {"kind", "schema_version", "cell_id", "sequence", "previous", "observation_sha256"}:
            raise ValueError("cell deadline observation anchor has invalid fields")
        cell_id = _identifier(event["cell_id"], "cell identity")
        claim = governance["cell_claims"].get(cell_id)
        sequence = _integer(event["sequence"], "cell observation sequence", 1)
        previous, digest = _sha(event["previous"]), _sha(event["observation_sha256"])
        if claim is None or sequence != claim["observation_sequence"] + 1 or previous != claim["observation_sha256"]:
            raise ValueError("cell deadline observation anchor is not consecutive")
        claim.update(observation_sequence=sequence, observation_sha256=digest)
    elif kind == "anchor_response_eligibility":
        if set(event) != {"kind", "schema_version", "run_id", "call_id", "cell_id",
                          "sequence", "observation_sha256", "proof_sha256"}:
            raise ValueError("response eligibility anchor has invalid fields")
        run_id = _sha(event['run_id'])
        call_id = _identifier(event['call_id'], 'call identity')
        cell_id = _identifier(event['cell_id'], 'cell identity')
        sequence = _integer(event['sequence'], 'cell observation sequence', 1)
        digest = _sha(event['observation_sha256'])
        proof = _sha(event['proof_sha256'])
        claim = governance['cell_claims'].get(cell_id)
        binding = governance['deadline_bindings'].get(run_id)
        operation = operations.get(call_id)
        if claim is None or binding is None or binding['cell_id'] != cell_id or operation is None or \
                operation.get('run_id') != run_id or claim['observation_sequence'] != sequence or \
                claim['observation_sha256'] != digest or call_id in governance['response_eligibility']:
            raise ValueError('response eligibility must bind the current original call and clock')
        governance['response_eligibility'][call_id] = {'run_id': run_id, 'cell_id': cell_id,
            'sequence': sequence, 'observation_sha256': digest, 'proof_sha256': proof}
    elif kind == "claim_cell_worker":
        if set(event) != {"kind", "schema_version", "cell_id", "deadline_ref", "worker_ref"}:
            raise ValueError("cell worker claim has invalid fields")
        cell_id = _identifier(event["cell_id"], "cell identity")
        deadline_ref, worker_ref = _sha(event["deadline_ref"]), _sha(event["worker_ref"])
        clock = governance["cell_claims"].get(cell_id)
        if clock is None or clock["record_sha256"] != deadline_ref:
            raise ValueError("cell worker requires the original deadline")
        if cell_id in governance["worker_claims"]:
            raise ValueError("cell worker was already claimed")
        governance["worker_claims"][cell_id] = {"deadline_ref": deadline_ref, "worker_ref": worker_ref}
    elif kind == "bind_run_deadline":
        if set(event) != {"kind", "schema_version", "run_id", "cell_id", "plan_ref", "deadline_ref"}:
            raise ValueError("run deadline binding has invalid fields")
        run_id = _sha(event["run_id"])
        _run(governance, run_id)
        cell_id = _identifier(event["cell_id"], "cell identity")
        claim = governance["cell_claims"].get(cell_id)
        value = {"cell_id": cell_id, "plan_ref": _plan_ref(event["plan_ref"]),
                 "deadline_ref": _sha(event["deadline_ref"])}
        if claim is None or claim["plan_ref"] != value["plan_ref"] or \
                claim["record_sha256"] != value["deadline_ref"] or \
                run_id in governance["deadline_bindings"] or \
                any(operation.get("run_id") == run_id for operation in operations.values()):
            raise ValueError("run deadline must bind the original cell before paid work")
        governance["deadline_bindings"][run_id] = value
    elif kind == "protect_run":
        if set(event) != {"kind", "schema_version", "run_id", "plan_ref", "obligations"}:
            raise ValueError("currency protection event has invalid fields")
        run_id, plan_ref = _sha(event["run_id"]), _plan_ref(event["plan_ref"])
        obligations = _obligations(policy, run_id, plan_ref, event["obligations"])
        if obligations != event["obligations"] or run_id in governance["runs"]:
            raise ValueError("currency protection is duplicated or not canonical")
        amount = sum(value["bound"]["reserved_micro_cny"] for value in obligations)
        if pending is not None or governance["breaches"] or spent + _outstanding(governance) + amount > policy["limit_micro_cny"]:
            raise ValueError("currency protected capacity unavailable or usage unresolved")
        governance["runs"][run_id] = {"plan_ref": plan_ref, "frozen": obligations,
            "obligations": [{**value, "status": "pending", "call_id": None, "reason": None}
                            for value in obligations]}
    elif kind == "governed_reserve":
        required = {"kind", "schema_version", "call_id", "run_id", "plan_ref", "lane", "slot_id",
                    "phase", "ordinal", "request_sha256", "output_allowance", "reserved_micro_cny"}
        if set(event) != required:
            raise ValueError("governed currency reservation shape is invalid")
        call_id = _identifier(event["call_id"], "call identity")
        run = _run(governance, event["run_id"], event["plan_ref"])
        _sha(event["request_sha256"])
        _integer(event["ordinal"], "provider ordinal")
        _identifier(event["phase"], "call phase")
        bound = _call_bound(policy, {"schema_version": 1,
            "output_allowance": event["output_allowance"], "reserved_micro_cny": event["reserved_micro_cny"]})
        if pending is not None:
            raise ValueError("campaign has unresolved provider usage; no new paid request allowed")
        if governance["breaches"]:
            raise ValueError("currency bound breach invalidated protection")
        if call_id in operations:
            raise ValueError("campaign call identity was already consumed")
        lane, slot, obligation = event["lane"], event["slot_id"], None
        released = 0
        if lane == "main" and slot is None:
            pass
        elif lane == "control":
            _identifier(slot, "control slot")
            obligation = _obligation(run, slot, event["phase"], event["ordinal"])
            if obligation["status"] != "pending":
                raise ValueError("control currency obligation is already consumed or cancelled")
            if bound["reserved_micro_cny"] > obligation["bound"]["reserved_micro_cny"]:
                raise ValueError("call exceeds its frozen currency obligation")
            released = obligation["bound"]["reserved_micro_cny"]
        else:
            raise ValueError("currency lane and control slot are inconsistent")
        if spent + _outstanding(governance) - released + bound["reserved_micro_cny"] > policy["limit_micro_cny"]:
            raise ValueError("campaign CNY budget exhausted by protected obligations")
        if obligation is not None:
            obligation.update(status="admitted", call_id=call_id)
        operations[call_id] = dict(event)
        pending = call_id
    elif kind == "governed_settle":
        if set(event) != {"kind", "schema_version", "call_id", "usage", "response_sha256",
                          "upper_bound_micro_cny", "bound_violation"}:
            raise ValueError("governed currency settlement shape is invalid")
        call_id = _identifier(event["call_id"], "call identity")
        old = operations.get(call_id)
        if pending != call_id or old is None or old["kind"] != "governed_reserve":
            raise ValueError("governed settlement lacks its admitted reservation")
        usage = validate_detailed_usage(event["usage"])
        _sha(event["response_sha256"])
        cost = usage["prompt_tokens"] * 2 + usage["completion_tokens"] * 8
        violated = (usage["prompt_tokens"] > policy["context_tokens"]
                    or usage["completion_tokens"] > old["output_allowance"]
                    or cost > old["reserved_micro_cny"])
        if usage != event["usage"] or type(event["upper_bound_micro_cny"]) is not int \
                or cost != event["upper_bound_micro_cny"] or event["bound_violation"] is not violated:
            raise ValueError("governed settlement changed the full known charge or bound violation")
        old.update({key: value for key, value in event.items() if key not in {"kind", "schema_version"}})
        if old["lane"] == "control":
            obligation = _obligation(_run(governance, old["run_id"], old["plan_ref"]),
                                      old["slot_id"], old["phase"], old["ordinal"])
            obligation["status"] = "settled"
        if violated:
            governance["breaches"].append(call_id)
        spent += cost
        pending = None
    elif kind == "cancel_control":
        if set(event) != {"kind", "schema_version", "run_id", "plan_ref", "slot_id", "reason"}:
            raise ValueError("control currency cancellation shape is invalid")
        run = _run(governance, event["run_id"], event["plan_ref"])
        slot = _identifier(event["slot_id"], "control slot")
        reason = event["reason"]
        if type(reason) is not str or not reason.strip() or len(reason) > 256:
            raise ValueError("control cancellation requires a bounded reason")
        if pending is not None:
            raise ValueError("unresolved provider usage prevents control cancellation")
        affected = [value for value in run["obligations"] if value["slot_id"] == slot and value["status"] == "pending"]
        if not affected:
            raise ValueError("control cancellation has no unconsumed obligations")
        for value in affected:
            value.update(status="cancelled", reason=reason)
    else:
        raise ValueError("unknown version-two currency event")
    return pending, spent


def _reduce_history(policies, events, heads):
    """Reconstruct authority state from exact policy/event/head records."""
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
    governance = {"enabled": False, "runs": {}, "breaches": [], "cell_claims": {},
                  "deadline_bindings": {}, "worker_claims": {}, "circle_pilot": None, "circle_runtime": None,
                  "response_eligibility": {}}
    seq, previous = 0, ZERO_HASH
    for number, payload, recorded_hash in events:
        event = json.loads(payload)
        if number != seq + 1 or recorded_hash != _hash({"seq": number, "previous": previous, "event": event}):
            raise ValueError("campaign journal hash chain is damaged")
        if type(event) is not dict:
            raise ValueError("campaign event must be an object")
        if "schema_version" in event:
            pending, spent = _reduce_governance(event, policy, governance, operations, pending, spent,
                                                 seq=seq, previous=previous)
            seq, previous = number, recorded_hash
            continue
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
                    or pending is not None or call_id in operations or governance["breaches"]
                    or spent + reserve + _outstanding(governance) > limit):
                raise ValueError("campaign reservation violates admission policy")
            _sha(event["request_sha256"])
            operations[call_id] = dict(event)
            pending = call_id
        elif event.get("kind") == "settle":
            if set(event) != {"kind", "call_id", "usage", "response_sha256", "upper_bound_micro_cny"} or pending != call_id:
                raise ValueError("campaign settlement lacks its reservation")
            usage = validate_detailed_usage(event["usage"])
            reserve = operations[call_id]
            if reserve["kind"] != "reserve":
                raise ValueError("legacy settlement cannot complete a governed reservation")
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
    if heads != [(seq, previous)]:
        raise ValueError("campaign journal head differs from recorded history")
    reserved = operations[pending]["reserved_micro_cny"] if pending else 0
    return policy, {"seq": seq, "hash": previous, "operations": operations,
                    "pending": pending, "spent": spent, "reserved": reserved, "governance": governance}


def _audit_run(policy, state, run_id, plan_ref):
    """Project a run audit only from semantically reduced authority state."""
    run = _run(state["governance"], run_id, plan_ref)
    operations = [value for value in state["operations"].values() if value.get("run_id") == run_id]
    slots = {}
    for obligation in run["obligations"]:
        summary = slots.setdefault(obligation["slot_id"], {"planned": 0, "pending": 0,
            "admitted": 0, "settled": 0, "cancelled": 0})
        summary["planned"] += 1
        summary[obligation["status"]] += 1
    outstanding = sum(value["bound"]["reserved_micro_cny"] for value in run["obligations"]
                      if value["status"] == "pending")
    reserved = sum(value["reserved_micro_cny"] for value in operations if "usage" not in value)
    spent = sum(value["upper_bound_micro_cny"] for value in operations if "usage" in value)
    breaches = list(state["governance"]["breaches"])
    return {"schema_version": 1, "run_id": run_id, "plan_ref": plan_ref,
        "campaign_id": policy["campaign_id"], "policy_sha256": _hash(policy),
        "outstanding_micro_cny": outstanding, "reserved_micro_cny": reserved,
        "settled_upper_bound_micro_cny": spent,
        "campaign_settled_upper_bound_micro_cny": state["spent"],
        "campaign_outstanding_micro_cny": _outstanding(state["governance"]),
        "pending_calls": [value["call_id"] for value in operations if "usage" not in value],
        "campaign_pending_calls": [state["pending"]] if state["pending"] else [],
        "slots": slots, "breaches": breaches, "protection_valid": not breaches,
        "admission_open": state["pending"] is None and not breaches,
        "frozen_obligations": json.loads(_json(run["frozen"])),
        "operations": json.loads(_json(operations)),
        "invoice_verified": False,
        "journal_head": {"seq": state["seq"], "sha256": state["hash"]}}


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
        return _reduce_history(
            db.execute("SELECT payload FROM policy").fetchall(),
            db.execute("SELECT seq, payload, hash FROM events ORDER BY seq").fetchall(),
            db.execute("SELECT seq, hash FROM head").fetchall())

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
            if state["governance"]["breaches"]:
                raise ValueError("currency bound breach invalidated protection")
            if state["spent"] + amount + _outstanding(state["governance"]) > policy["limit_micro_cny"]:
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
            event = {"kind": "settle", "call_id": call_id, "usage": usage,
                     "response_sha256": response_sha256, "upper_bound_micro_cny": cost}
            if old is not None and old["kind"] == "governed_reserve":
                event.update(kind="governed_settle", schema_version=2,
                    bound_violation=(usage["prompt_tokens"] > _policy["context_tokens"]
                        or usage["completion_tokens"] > old["output_allowance"]
                        or cost > old["reserved_micro_cny"]))
            self._append(db, state, event)

    def snapshot(self):
        with self._transaction() as (_, policy, state):
            return {"campaign_id": policy["campaign_id"], "policy_sha256": _hash(policy),
                    "limit_micro_cny": policy["limit_micro_cny"], "invoice_verified": False,
                    "settled_upper_bound_micro_cny": state["spent"],
                    "reserved_micro_cny": state["reserved"],
                    "remaining_micro_cny": policy["limit_micro_cny"] - state["spent"] - state["reserved"]
                        - _outstanding(state["governance"]),
                    "pending_calls": [state["pending"]] if state["pending"] else [],
                    "operations": list(state["operations"].values()),
                    "journal_head": {"seq": state["seq"], "sha256": state["hash"]},
                    **({"journal_schema_version": 2, "protected_micro_cny": _outstanding(state["governance"]),
                        "protection_breaches": list(state["governance"]["breaches"])}
                       if state["governance"]["enabled"] else {})}

    def enable_governance(self, *, expected_policy_sha256, expected_head):
        """Explicitly enable v2 events without changing any policy or old row.

        Callers must arrange a quiescent lifecycle transition and validate the
        exact policy/head beforehand. This method never copies, resets or grants
        new funds. A v1 reader fails closed on the appended version marker.
        """
        _sha(expected_policy_sha256)
        _head_anchor(expected_head)
        with self._transaction() as (db, policy, state):
            if state["pending"] is not None:
                raise ValueError("unresolved provider usage prevents governance migration")
            if state["governance"]["enabled"]:
                raise ValueError("currency governance migration is already enabled")
            if expected_policy_sha256 != _hash(policy) or expected_head != {
                    "seq": state["seq"], "sha256": state["hash"]}:
                raise ValueError("currency migration policy or journal head anchor changed")
            self._append(db, state, {"kind": "governance_enabled", "schema_version": 2,
                "policy_sha256": expected_policy_sha256, "previous_head": dict(expected_head)})

    def quote_call(self, output_allowance):
        """Frozen peak-price total-call bound, with full context input capacity."""
        _integer(output_allowance, "output allowance", 1)
        with self._transaction() as (_, policy, _state):
            return _call_bound(policy, {"schema_version": 1, "output_allowance": output_allowance,
                "reserved_micro_cny": policy["context_tokens"] * 2 + output_allowance * 8})

    def claim_cell_deadline(self, cell_id, plan_ref, record_sha256, *, seconds=None):
        """Permanently bind one cell clock to this existing campaign journal."""
        _identifier(cell_id, "cell identity")
        _plan_ref(plan_ref)
        _sha(record_sha256)
        with self._transaction() as (db, _policy, state):
            if not state["governance"]["enabled"]:
                raise ValueError("cell deadline claim requires currency governance")
            event = {"kind": "claim_cell_deadline", "schema_version": 2,
                     "cell_id": cell_id, "plan_ref": plan_ref, "record_sha256": record_sha256}
            if state["governance"]["circle_pilot"] is not None:
                event["seconds"] = seconds
            self._append(db, state, event)

    def freeze_circle_pilot(self, plan_ref, tree_ref, wallclock_seconds, *, require_runtime=False):
        """Anchor one draft and source tree before any cell starts."""
        _plan_ref(plan_ref)
        _plan_ref(tree_ref)
        _integer(wallclock_seconds, "cell duration", 1)
        if type(require_runtime) is not bool:
            raise ValueError('runtime requirement must be boolean')
        with self._transaction() as (db, _policy, state):
            event = {"kind": "freeze_circle_pilot", "schema_version": 2,
                     "plan_ref": plan_ref, "tree_ref": tree_ref, "wallclock_seconds": wallclock_seconds}
            if require_runtime:
                event['require_runtime'] = True
            self._append(db, state, event)

    def circle_pilot_binding(self):
        with self._transaction() as (_db, _policy, state):
            value = state["governance"]["circle_pilot"]
            return dict(value) if value is not None else None

    def freeze_circle_runtime(self, plan_ref, tree_ref, runtime_ref, python_sha256):
        _plan_ref(plan_ref)
        _plan_ref(tree_ref)
        _plan_ref(runtime_ref)
        _sha(python_sha256)
        with self._transaction() as (db, _policy, state):
            self._append(db, state, {"kind": "freeze_circle_runtime", "schema_version": 2,
                                    "plan_ref": plan_ref, "tree_ref": tree_ref,
                                    "runtime_ref": runtime_ref, "python_sha256": python_sha256})

    def circle_runtime_binding(self):
        with self._transaction() as (_db, _policy, state):
            value = state["governance"]["circle_runtime"]
            return dict(value) if value is not None else None

    def anchor_cell_deadline_observation(self, cell_id, sequence, previous, observation_sha256):
        _identifier(cell_id, "cell identity")
        _integer(sequence, "cell observation sequence", 1)
        _sha(previous)
        _sha(observation_sha256)
        with self._transaction() as (db, _policy, state):
            self._append(db, state, {"kind": "observe_cell_deadline", "schema_version": 2,
                "cell_id": cell_id, "sequence": sequence, "previous": previous,
                "observation_sha256": observation_sha256})

    def cell_deadline_claim(self, cell_id):
        _identifier(cell_id, "cell identity")
        with self._transaction() as (_db, _policy, state):
            value = state["governance"]["cell_claims"].get(cell_id)
            return dict(value) if value is not None else None

    def anchor_response_eligibility(self, run_id, call_id, cell_id, sequence, observation_sha256, proof_sha256):
        with self._transaction() as (db, _policy, state):
            self._append(db, state, {'kind': 'anchor_response_eligibility', 'schema_version': 2,
                'run_id': run_id, 'call_id': call_id, 'cell_id': cell_id, 'sequence': sequence,
                'observation_sha256': observation_sha256, 'proof_sha256': proof_sha256})

    def response_eligibility(self, call_id):
        _identifier(call_id, 'call identity')
        with self._transaction() as (_db, _policy, state):
            value = state['governance']['response_eligibility'].get(call_id)
            return dict(value) if value is not None else None

    def claim_cell_worker(self, cell_id, deadline_ref, worker_ref):
        """Consume the one worker start for a cell in the original ledger."""
        _identifier(cell_id, "cell identity")
        _sha(deadline_ref)
        _sha(worker_ref)
        with self._transaction() as (db, _policy, state):
            self._append(db, state, {"kind": "claim_cell_worker", "schema_version": 2,
                                    "cell_id": cell_id, "deadline_ref": deadline_ref,
                                    "worker_ref": worker_ref})

    def cell_worker_claim(self, cell_id):
        _identifier(cell_id, "cell identity")
        with self._transaction() as (_db, _policy, state):
            value = state["governance"]["worker_claims"].get(cell_id)
            return dict(value) if value is not None else None

    def bind_run_deadline(self, run_id, cell_id, plan_ref, deadline_ref):
        _sha(run_id)
        _identifier(cell_id, "cell identity")
        _plan_ref(plan_ref)
        _sha(deadline_ref)
        value = {"cell_id": cell_id, "plan_ref": plan_ref, "deadline_ref": deadline_ref}
        with self._transaction() as (db, _policy, state):
            existing = state["governance"]["deadline_bindings"].get(run_id)
            if existing is not None:
                if existing != value:
                    raise ValueError("run deadline binding cannot change")
                return
            self._append(db, state, {"kind": "bind_run_deadline", "schema_version": 2,
                                    "run_id": run_id, **value})

    def run_deadline_binding(self, run_id):
        _sha(run_id)
        with self._transaction() as (_db, _policy, state):
            value = state["governance"]["deadline_bindings"].get(run_id)
            return dict(value) if value is not None else None

    def protect_run(self, run_id, plan_ref, obligations):
        _sha(run_id)
        _plan_ref(plan_ref)
        with self._transaction() as (db, policy, state):
            governance = state["governance"]
            if not governance["enabled"]:
                raise ValueError("explicit currency governance migration must enable protection first")
            frozen = _obligations(policy, run_id, plan_ref, obligations)
            previous = governance["runs"].get(run_id)
            if previous is not None:
                if previous["plan_ref"] == plan_ref and previous["frozen"] == frozen:
                    return
                raise ValueError("protected currency run cannot change its frozen plan or obligations")
            self._append(db, state, {"kind": "protect_run", "schema_version": 2,
                "run_id": run_id, "plan_ref": plan_ref, "obligations": frozen})

    def admit_call(self, run_id, lane, slot_id, call_binding, bound):
        """Commit a real reservation and consume its control obligation atomically.

        A successful return authorizes currency capacity only. The caller must
        also durably admit its physical reservation before issuing any request.
        A repeated unresolved call is rejected, never automatically retried.
        """
        if type(call_binding) is not dict or set(call_binding) != {
                "call_id", "request_sha256", "phase", "ordinal"}:
            raise ValueError("currency call binding requires call, request, phase and ordinal")
        with self._transaction() as (db, policy, state):
            run = _run(state["governance"], run_id)
            bound = _call_bound(policy, bound)
            self._append(db, state, {"kind": "governed_reserve", "schema_version": 2,
                "run_id": run_id, "plan_ref": run["plan_ref"], "lane": lane, "slot_id": slot_id,
                **call_binding, "output_allowance": bound["output_allowance"],
                "reserved_micro_cny": bound["reserved_micro_cny"]})

    def cancel_control(self, run_id, slot_id, *, reason):
        """Release only untouched obligations after an authoritative slot failure."""
        with self._transaction() as (db, _policy, state):
            run = _run(state["governance"], run_id)
            # A repeated identical cancellation is harmless after crash adoption.
            affected = [value for value in run["obligations"] if value["slot_id"] == slot_id]
            cancelled = [value for value in affected if value["status"] == "cancelled"]
            if cancelled and all(value["status"] in {"settled", "cancelled"} for value in affected):
                if all(value["reason"] == reason for value in cancelled):
                    return
                raise ValueError("control cancellation reason cannot be changed")
            self._append(db, state, {"kind": "cancel_control", "schema_version": 2,
                "run_id": run_id, "plan_ref": run["plan_ref"], "slot_id": slot_id, "reason": reason})

    def audit_run(self, run_id, plan_ref):
        """Recompute currency obligations and charges from the current journal."""
        with self._transaction() as (_, policy, state):
            return _audit_run(policy, state, run_id, plan_ref)

    def export_governance_evidence(self, run_id, plan_ref):
        """Export a private, complete campaign prefix from one read snapshot.

        The returned proof describes this recorded head, not future live balance.
        It includes other runs because their charges constrain shared capacity.
        No authority events or database schema are changed.
        """
        _sha(run_id)
        _plan_ref(plan_ref)
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("existing regular campaign ledger is required")
        if stat.S_IMODE(self.path.stat().st_mode) != 0o600:
            raise ValueError("campaign ledger must have private 0600 permissions")
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True,
                                 isolation_level=None, timeout=30)
            db.execute("BEGIN")
            policies = db.execute("SELECT payload FROM policy").fetchall()
            events = db.execute("SELECT seq, payload, hash FROM events ORDER BY seq").fetchall()
            heads = db.execute("SELECT seq, hash FROM head").fetchall()
            policy, state = _reduce_history(policies, events, heads)
            if self._binding is not None and policy != self._binding:
                raise ValueError("campaign identity or policy changed")
            _run(state["governance"], run_id, plan_ref)
            evidence = {"schema_version": 1, "run_id": run_id, "plan_ref": plan_ref,
                "policy_json": policies[0][0], "policy_sha256": _hash(policy),
                "events": [{"seq": number, "payload": payload, "sha256": hashed}
                           for number, payload, hashed in events],
                "journal_head": {"seq": state["seq"], "sha256": state["hash"]}}
            db.execute("COMMIT")
            return evidence
        except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError(f"campaign ledger integrity failed ({type(error).__name__})") from None
        finally:
            if db is not None:
                db.close()
