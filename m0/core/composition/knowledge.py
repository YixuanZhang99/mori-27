"""Offline M6 adapter with opened local sources and independent query lanes.

Construction reads and binds explicitly configured files, but never searches,
writes a journal, opens a network connection, or guesses an unknown cost. This
backend declares zero provider usage because all work is local deterministic
text retrieval; live paid backends need a different metered plugin.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.composition.context import ContextMemory
from core.composition.contracts import json_copy
from core.executor.types import CostVec
from core.knowledge.service import KnowledgeService
from core.knowledge.types import (AuditReliability, AuditVerdict, DualRateLedger,
                                  FetchedDocument, GroundedQuery)
from core.memory.store import ScopedMemory, similarity
from core.memory.types import ScopeContext


def _json(value):
    return json.dumps(json_copy(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _hash(_json(value).encode("utf-8"))


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


def _read_snapshot(path, expected_sha256):
    raw = Path(path).read_bytes()
    if _hash(raw) != expected_sha256:
        raise ValueError("knowledge import content hash mismatch")
    return json_copy(json.loads(raw), label="knowledge import")


def knowledge_options(options):
    if type(options) is not dict or set(options) - {"ground_files", "audit_files", "max_results",
            "max_file_bytes", "ground_namespace", "audit_namespace", "memory_imports", "ingest_on_finish"}:
        raise ValueError("unknown local knowledge options")
    if not {"ground_files", "audit_files"}.issubset(options):
        raise ValueError("knowledge requires independently configured ground_files and audit_files")
    for key in ("ground_files", "audit_files"):
        if type(options[key]) is not list:
            raise ValueError("knowledge file lists must be arrays")
        for spec in options[key]:
            if type(spec) is not dict or set(spec) - {"path", "sha256"} or "path" not in spec:
                raise ValueError("knowledge file spec requires path and optional sha256")
            _text(spec["path"], "knowledge source path")
            if "sha256" in spec and (type(spec["sha256"]) is not str
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", spec["sha256"])):
                raise ValueError("knowledge source sha256 is invalid")
    for key, default, maximum in (("max_results", 5, 100), ("max_file_bytes", 1048576, 16777216)):
        value = options.get(key, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"{key} must be a positive integer <= {maximum}")
    for key, default in (("ground_namespace", "ground"), ("audit_namespace", "audit")):
        _text(options.get(key, default), "lane namespace")
    if options.get("ground_namespace", "ground") == options.get("audit_namespace", "audit"):
        raise ValueError("knowledge lane namespaces must be disjoint")
    if "ingest_on_finish" in options and type(options["ingest_on_finish"]) is not bool:
        raise ValueError("ingest_on_finish must be boolean")
    imports = options.get("memory_imports", [])
    if type(imports) is not list:
        raise ValueError("knowledge memory_imports must be an array")
    for item in imports:
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise ValueError("knowledge memory import requires exactly path and sha256")
        _text(item["path"], "knowledge memory import path")
        if type(item["sha256"]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["sha256"]):
            raise ValueError("knowledge memory import requires an explicit content hash")


class LocalFilesBackend:
    def __init__(self, specs, *, max_file_bytes=1048576, max_results=5):
        self.calls = []
        self.max_results = max_results
        self.documents = []
        self.manifest = []
        seen = set()
        for spec in specs:
            path = Path(spec["path"]).expanduser().resolve(strict=True)
            if not path.is_file() or path in seen:
                raise ValueError("knowledge source must be a distinct regular file")
            seen.add(path)
            # A bounded read also rejects a file that grew after stat().
            with path.open("rb") as stream:
                raw = stream.read(max_file_bytes + 1)
            if len(raw) > max_file_bytes:
                raise ValueError("knowledge source exceeds max_file_bytes")
            text = raw.decode("utf-8")
            if not text.strip():
                raise ValueError("knowledge source has no opened text")
            digest = _hash(raw)
            if spec.get("sha256", digest) != digest:
                raise ValueError("knowledge source content hash mismatch")
            self.documents.append(FetchedDocument(path.as_uri(), text, "local-files", opened=True))
            self.manifest.append({"uri": path.as_uri(), "sha256": digest, "size_bytes": len(raw)})
        self.documents.sort(key=lambda document: document.url)
        self.manifest.sort(key=lambda source: source["uri"])

    def search(self, text, lane):
        _text(text, "knowledge search query")
        if lane not in {"ground", "audit"}:
            raise ValueError("unknown knowledge lane")
        self.calls.append({"query": text, "lane": lane})
        return sorted(self.documents, key=lambda document:
                      (-similarity(text, document.content), document.url))[:self.max_results]


@dataclass(frozen=True)
class KnowledgePack:
    _encoded: str
    cost: CostVec = field(default_factory=CostVec)

    def to_dict(self):
        return json.loads(self._encoded)

    def context_items(self):
        value = self.to_dict()
        if value["lane"] != "ground":
            raise ValueError("only ground knowledge may enter candidate context")
        return value["items"]

    @property
    def ref(self):
        return _hash(self._encoded.encode("utf-8"))


@dataclass(frozen=True)
class KnowledgeAudit:
    _encoded: str
    cost: CostVec = field(default_factory=CostVec)

    def to_dict(self):
        return json.loads(self._encoded)


class _QuietStore:
    def append(self, kind, payload):
        pass


class LocalKnowledge:
    def __init__(self, options, store, *, mode):
        # Benchmark rejection precedes even filesystem reads or constructors.
        if mode != "research":
            raise ValueError("knowledge requires explicit research mode; benchmark access is disabled")
        knowledge_options(options)
        self.options = json_copy(options)
        self.store, self.mode = store, mode
        limits = {key: options.get(key, default) for key, default in
                  (("max_file_bytes", 1048576), ("max_results", 5))}
        self.ground_backend = LocalFilesBackend(options["ground_files"], **limits)
        # Audit searches at least the ground universe, using a separate reader
        # and search history. Matching fetched text still invalidates a verdict.
        audit_specs = list(options["audit_files"])
        audit_paths = [Path(spec["path"]).expanduser().resolve(strict=True) for spec in audit_specs]
        if len(set(audit_paths)) != len(audit_paths):
            raise ValueError("audit sources must be distinct regular files")
        audit_universe = set(audit_paths)
        audit_specs.extend(spec for spec in options["ground_files"]
                           if Path(spec["path"]).expanduser().resolve(strict=True) not in audit_universe)
        self.audit_backend = LocalFilesBackend(audit_specs, **limits)
        audit_by_uri = {item["uri"]: item["sha256"] for item in self.audit_backend.manifest}
        if any(audit_by_uri[item["uri"]] != item["sha256"] for item in self.ground_backend.manifest):
            raise ValueError("ground source changed while binding the audit corpus")
        self.namespaces = {"ground": options.get("ground_namespace", "ground"),
                           "audit": options.get("audit_namespace", "audit")}
        self._service = None
        self.records = {}
        self.imports = {}

    @property
    def manifest_binding(self):
        return {"kind": "local-files-v1", "mode": self.mode, "namespaces": dict(self.namespaces),
                "max_results": self.options.get("max_results", 5),
                "ground": copy.deepcopy(self.ground_backend.manifest),
                "audit": copy.deepcopy(self.audit_backend.manifest)}

    def _make_service(self, store):
        return KnowledgeService(self.ground_backend, self.audit_backend, store,
            {"local-files"}, {"local-files"}, self.namespaces["ground"], self.namespaces["audit"])

    def _active(self):
        if self.mode != "research":
            raise ValueError("knowledge mode changed after construction")
        if self._service is None:
            self._service = self._make_service(self.store)
        return self._service

    def _invalidate_overlap(self):
        service = self._active()
        # Ground fetched after audit must invalidate that earlier verdict too.
        for audit_id, audit in service.audits.items():
            contaminated = [ref for ref in audit.fetch_refs
                            if service.fetch_by_ref[ref]["content_hash"] in service.hashes_by_lane["ground"]]
            if contaminated and audit_id not in service.invalidated_audits:
                service.invalidated_audits.add(audit_id)
                self.store.append("knowledge_verdict_invalidation", {"audit_id": audit_id,
                    "reason": "cross-lane fetched-text overlap", "fetch_refs": contaminated,
                    "error_kind": "isolation_violation"})

    def ground(self, query_id, text, *, intent="lookup", context=None):
        if intent not in {"related_work", "survey", "lookup", "explore", "repair"}:
            raise ValueError("unknown grounding intent")
        depth = "mid" if intent == "repair" else "shallow_2k" if intent == "lookup" else "deep_6k"
        query = GroundedQuery(query_id, intent, text, json_copy(context or {}), depth, "research")
        digest = self._active().query(query)
        self._invalidate_overlap()
        item = {"digest_id": digest.digest_id, "tier": "TIER2", "summary": digest.summary,
                "findings": digest.findings, "fetch_refs": digest.sources,
                "provenance": digest.provenance, "ranking": "local lexical relevance"}
        return KnowledgePack(_json({"schema_version": 1, "lane": "ground", "items": [item]}))

    def audit(self, idea_id, idea_text, *, phase="add_precheck"):
        if phase not in {"add_precheck", "merge_review"}:
            raise ValueError("unknown novelty audit phase")
        _text(idea_text, "candidate artifact")
        verdict = self._active().audit(idea_id, idea_text, phase, "research")
        self._invalidate_overlap()
        return KnowledgeAudit(_json({"verdict": asdict(verdict),
            "advisory_only": True, "invalidated": verdict.audit_id in self._service.invalidated_audits}))

    def invalidate_evidence(self, evidence_refs, reason):
        _text(reason, "invalidation reason")
        if not isinstance(evidence_refs, set) or any(type(ref) is not str for ref in evidence_refs):
            raise ValueError("knowledge invalidation requires evidence reference strings")
        affected = []
        for identifier, record in self.records.items():
            if evidence_refs.intersection(record["evidence_refs"]) and record["invalidated"] is None:
                record["invalidated"] = reason
                affected.append(identifier)
        if affected:
            self.store.append("knowledge_evidence_invalidation", {"record_ids": sorted(affected),
                               "evidence_refs": sorted(evidence_refs), "reason": reason})
        return sorted(affected)

    def _prepare_memory_import(self, path, expected_sha256):
        payload = _read_snapshot(path, expected_sha256)
        if type(payload) is not dict or set(payload) != {"schema_version", "kind", "evaluation_context", "entries", "bindings"} \
                or type(payload["schema_version"]) is not int or payload["schema_version"] != 1 \
                or payload["kind"] != "composed-memory-export" or type(payload["entries"]) is not list \
                or not payload["entries"] or type(payload["bindings"]) is not dict:
            raise ValueError("knowledge ingest requires a memory export snapshot")
        if not payload["evaluation_context"]:
            raise ValueError("opaque evaluation context cannot authorize knowledge ingest")
        if expected_sha256 in self.imports:
            return {}
        prepared = {}
        for data in payload["entries"]:
            context = ScopeContext(**data["context"])
            memory = ContextMemory(self.store, context, payload["evaluation_context"])
            ScopedMemory.restore_state(memory, {"seq": 1, "entries": [data]})
            memory.bindings = payload["bindings"]
            entry = next(iter(memory.entries.values()))
            memory._validate_entry(entry, imported=True)
            if entry.scope == "run" or entry.state != "active" or entry.level not in {"L2", "L3"} \
                    or entry.time.superseded_by is not None:
                raise ValueError("knowledge ingest requires valid active L2/L3 lessons")
            identifier = "knowledge:" + _digest([expected_sha256, entry.id])[7:]
            prepared[identifier] = {"id": identifier, "kind": "heuristic",
                "statement": copy.deepcopy(entry.payload.body), "source_snapshot": expected_sha256,
                "source_entry_id": entry.id, "evidence_refs": list(entry.provenance.evidence_refs),
                "context": asdict(entry.context), "scope": entry.scope,
                "evaluation_context": payload["evaluation_context"], "invalidated": None}
        if set(prepared).intersection(self.records):
            raise ValueError("knowledge ingest would overwrite an existing record")
        return prepared

    def validate_memory_import(self, path, *, expected_sha256):
        """Pure startup read/validation; safe before resume compatibility checks."""
        prepared = self._prepare_memory_import(path, expected_sha256)
        return {"path": str(Path(path).resolve()), "sha256": expected_sha256,
                "record_ids": list(self.imports.get(expected_sha256, sorted(prepared)))}

    def ingest_memory_export(self, path, *, expected_sha256):
        """Explicit M5→M6 transfer; M6 never scans a memory store or ambient path."""
        prepared = self._prepare_memory_import(path, expected_sha256)
        if expected_sha256 in self.imports:
            return list(self.imports[expected_sha256])
        self.records.update(prepared)
        self.imports[expected_sha256] = sorted(prepared)
        self.store.append("knowledge_ingest", {"source_snapshot": expected_sha256,
                           "record_ids": sorted(prepared), "cost": asdict(CostVec())})
        return sorted(prepared)

    def retrieve(self, scope_context, query, *, evaluation_context, top_k=5):
        if not isinstance(scope_context, ScopeContext) or type(top_k) is not int or top_k < 1:
            raise ValueError("knowledge retrieval requires an explicit scope and positive top_k")
        _text(query, "knowledge retrieval query")
        visible = [record for record in self.records.values()
                   if record["invalidated"] is None
                   and record["evaluation_context"] == evaluation_context
                   and record["context"]["domain_id"] == scope_context.domain_id
                   and (record["scope"] == "domain"
                        or record["context"]["task_id"] == scope_context.task_id)]
        ranked = sorted(visible, key=lambda record:
                        (-similarity(query, str(record["statement"])), record["id"]))[:top_k]
        items = [{"digest_id": record["id"], "tier": "TIER2", "summary": "Imported run heuristic",
                  "findings": [copy.deepcopy(record["statement"])], "fetch_refs": [],
                  "provenance": {"lane": "ground", "source_snapshot": record["source_snapshot"],
                      "source_entry_id": record["source_entry_id"], "evidence_refs": record["evidence_refs"]},
                  "ranking": "scoped local lexical relevance"} for record in ranked]
        self.store.append("knowledge_retrieve", {"record_ids": [record["id"] for record in ranked],
                          "query": query, "scope": asdict(scope_context), "cost": asdict(CostVec())})
        return KnowledgePack(_json({"schema_version": 1, "lane": "ground", "items": items}))

    def checkpoint_state(self):
        service = self._service
        state = None if service is None else {
            "seq": service._seq, "fetch_by_ref": service.fetch_by_ref,
            "hashes_by_lane": {lane: sorted(values) for lane, values in service.hashes_by_lane.items()},
            "audits": {key: asdict(value) for key, value in service.audits.items()},
            "invalidated_audits": sorted(service.invalidated_audits),
            "reviews": [asdict(value) for value in service.reviews]}
        return json_copy({"schema_version": 1, "manifest": self.manifest_binding,
            "service": state, "records": self.records, "imports": self.imports,
            "ground_calls": self.ground_backend.calls, "audit_calls": self.audit_backend.calls})

    def restore_state(self, state):
        state = json_copy(state, label="knowledge checkpoint")
        if type(state) is not dict or set(state) != {"schema_version", "manifest", "service", "records", "imports", "ground_calls", "audit_calls"} \
                or type(state["schema_version"]) is not int or state["schema_version"] != 1 \
                or state["manifest"] != self.manifest_binding or type(state["records"]) is not dict \
                or type(state["imports"]) is not dict:
            raise ValueError("knowledge checkpoint configuration mismatch")
        if self._service is not None or self.records or self.imports:
            raise ValueError("knowledge restore requires a fresh component")
        for lane in ("ground", "audit"):
            calls = state[f"{lane}_calls"]
            if type(calls) is not list or any(type(call) is not dict or set(call) != {"query", "lane"}
                    or type(call["query"]) is not str or call["lane"] != lane for call in calls):
                raise ValueError("invalid knowledge backend checkpoint")
        for key, record in state["records"].items():
            if type(record) is not dict or record.get("id") != key or record.get("kind") != "heuristic" \
                    or record.get("scope") not in {"task", "domain"} \
                    or not isinstance(record.get("evidence_refs"), list) or not record["evidence_refs"]:
                raise ValueError("invalid knowledge record checkpoint")
        for digest, identifiers in state["imports"].items():
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or type(identifiers) is not list \
                    or any(identifier not in state["records"] for identifier in identifiers):
                raise ValueError("invalid knowledge import checkpoint")
        value = state["service"]
        service = None
        if value is not None:
            service = self._make_service(_QuietStore())
            if type(value) is not dict or set(value) != {"seq", "fetch_by_ref", "hashes_by_lane", "audits", "invalidated_audits", "reviews"} \
                    or type(value["seq"]) is not int or value["seq"] < 0 \
                    or type(value["fetch_by_ref"]) is not dict or len(value["fetch_by_ref"]) != value["seq"]:
                raise ValueError("invalid knowledge fetch checkpoint")
            rebuilt_hashes = {"ground": set(), "audit": set()}
            for number in range(1, value["seq"] + 1):
                ref = f"fetch:{number}"
                fetch = value["fetch_by_ref"].get(ref, {})
                lane = fetch.get("lane")
                if lane not in rebuilt_hashes or fetch.get("seq") != number or fetch.get("ref") != ref \
                        or fetch.get("namespace") != self.namespaces[lane] \
                        or not re.fullmatch(r"[0-9a-f]{64}", fetch.get("content_hash", "")):
                    raise ValueError("invalid knowledge fetch identity")
                rebuilt_hashes[lane].add(fetch["content_hash"])
            if value["hashes_by_lane"] != {lane: sorted(items) for lane, items in rebuilt_hashes.items()}:
                raise ValueError("knowledge hash checkpoint differs from fetch ledger")
            audits = {}
            for identifier, data in value["audits"].items():
                data = dict(data)
                data["reliability"] = AuditReliability(**data["reliability"])
                audit = AuditVerdict(**data)
                if audit.audit_id != identifier or audit.lane != "audit" \
                        or any(ref not in value["fetch_by_ref"] or value["fetch_by_ref"][ref]["lane"] != "audit"
                               for ref in audit.fetch_refs):
                    raise ValueError("invalid knowledge audit checkpoint")
                audits[identifier] = audit
            invalidated = set(value["invalidated_audits"])
            if not invalidated.issubset(audits):
                raise ValueError("invalidated audit does not exist")
            for identifier, audit in audits.items():
                overlap = any(value["fetch_by_ref"][ref]["content_hash"] in rebuilt_hashes["ground"]
                              for ref in audit.fetch_refs)
                if overlap and identifier not in invalidated:
                    raise ValueError("knowledge checkpoint revived an invalid audit")
            service._seq, service.fetch_by_ref = value["seq"], value["fetch_by_ref"]
            service.hashes_by_lane, service.audits = rebuilt_hashes, audits
            service.invalidated_audits = invalidated
            service.reviews = [DualRateLedger(**review) for review in value["reviews"]]
            service.store = self.store
        self._service, self.records, self.imports = service, state["records"], state["imports"]
        self.ground_backend.calls, self.audit_backend.calls = state["ground_calls"], state["audit_calls"]
