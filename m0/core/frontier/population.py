"""Population membership is a bounded view of the authoritative research DAG.

Retention uses only successful public development scores. It does not decide
M9 promotion: a gate-rejected but valid development candidate may remain a
parent, while the driver-selected incumbent is protected within capacity.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict

from core.executor.types import EvalStatus
from core.frontier.research import (FrontierCheckpoint, MUTABLE_FIELDS,
                                   ResearchFrontier, _digest)

_SELECTIONS = {"greedy", "uniform", "tournament", "softmax"}


def population_options(options):
    allowed = {"metric", "direction", "sample_seed", "capacity", "retention", "selection",
               "tournament_size", "temperature"}
    if type(options) is not dict or set(options) - allowed:
        raise ValueError("unknown population frontier options")
    metric = options.get("metric", "dev/score")
    if type(metric) is not str or not metric.strip():
        raise ValueError("population requires a development metric")
    if options.get("direction", "maximize") not in ("maximize", "minimize"):
        raise ValueError("population direction must be maximize or minimize")
    for key, default, minimum in (("capacity", 32, 1), ("tournament_size", 3, 1), ("sample_seed", 0, 0)):
        if type(options.get(key, default)) is not int or options.get(key, default) < minimum:
            raise ValueError(f"population {key} must be an integer >= {minimum}")
    if options.get("retention", "elite") != "elite":
        raise ValueError("only deterministic elite retention is implemented")
    if type(options.get("selection", "tournament")) is not str or options.get("selection", "tournament") not in _SELECTIONS:
        raise ValueError("unknown population selection pressure")
    temperature = options.get("temperature", 1.0)
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("population temperature must be finite and positive")


class PopulationFrontier(ResearchFrontier):
    def __init__(self, metric="dev/score", direction="maximize", sample_seed=0, store=None,
                 git_state=None, messages=None, *, capacity=32, retention="elite",
                 selection="tournament", tournament_size=3, temperature=1.0):
        settings = {"metric": metric, "direction": direction, "sample_seed": sample_seed,
                    "capacity": capacity, "retention": retention, "selection": selection,
                    "tournament_size": tournament_size, "temperature": temperature}
        population_options(settings)
        super().__init__(metric, direction, sample_seed, store, git_state, messages)
        self.capacity, self.retention, self.selection = capacity, retention, selection
        self.tournament_size, self.temperature = tournament_size, temperature
        self._members, self._outcomes, self._protected_id = set(), {}, None
        self._rng = {"counter": 0, "calls": 0}
        self._sampling_receipts = []

    @property
    def member_ids(self):
        return tuple(sorted(self._members))

    @property
    def protected_id(self):
        return self._protected_id

    @property
    def sampling_receipts(self):
        return copy.deepcopy(self._sampling_receipts)

    @property
    def rng_state(self):
        return dict(self._rng)

    def _config(self):
        return {"metric": self.metric, "direction": self.direction, "sample_seed": self.sample_seed,
                "capacity": self.capacity, "retention": self.retention, "selection": self.selection,
                "tournament_size": self.tournament_size, "temperature": self.temperature}

    def _rank_key(self, node):
        return (-node.score if self.direction == "maximize" else node.score, node.created_cycle, node.id)

    @staticmethod
    def _valid_parent(node):
        return node.status in {"done", "merged"} and node.eval_status == EvalStatus.OK.value \
            and type(node.score) in (int, float) and math.isfinite(node.score)

    def _retained(self, *, nodes=None, outcomes=None, protected=None):
        nodes = self.nodes if nodes is None else nodes
        outcomes = self._outcomes if outcomes is None else outcomes
        eligible = sorted((nodes[identifier] for identifier in outcomes if self._valid_parent(nodes[identifier])),
                          key=self._rank_key)
        if protected is not None and (protected not in outcomes or not self._valid_parent(nodes[protected])
                                      or not outcomes[protected]["admitted"]):
            raise ValueError("selected incumbent must have a valid admitted development node")
        retained = [protected] if protected is not None else []
        retained.extend(node.id for node in eligible if node.id != protected)
        return set(retained[:self.capacity])

    def finalize(self, node, *, admitted, reason, selected_id, decision_ref):
        """Driver-only population outcome after M9; never called by M1 absorb."""
        target = self._node(node)
        if node in self._outcomes:
            raise ValueError("population candidate outcome cannot be rebound")
        if type(admitted) is not bool or type(reason) is not str or not reason.strip() \
                or type(decision_ref) is not str or not decision_ref.strip():
            raise ValueError("population requires a concrete M9 decision and receipt reference")
        if target.status != "done" or admitted and not self._valid_parent(target):
            raise ValueError("only an evaluated valid node can be admitted")
        if selected_id != (node if admitted else self._protected_id):
            raise ValueError("population cannot invent or replace the driver-selected incumbent")
        nodes, outcomes = dict(self.nodes), dict(self._outcomes)
        updated = copy.deepcopy(target)
        updated.status = "merged" if admitted else "done" if self._valid_parent(target) else "pruned"
        if updated.status == "pruned":
            updated.prune_reason = reason
        nodes[node] = updated
        outcomes[node] = {"admitted": admitted, "reason": reason, "selected_id": selected_id,
                          "decision_ref": decision_ref}
        members = self._retained(nodes=nodes, outcomes=outcomes, protected=selected_id)
        receipt = {"candidate_id": node, **outcomes[node], "members": sorted(members),
                   "evicted": sorted(self._members - members), "protected_id": selected_id}
        self._emit("population_finalized", receipt)
        self.nodes[node], self._outcomes, self._members, self._protected_id = updated, outcomes, members, selected_id
        return copy.deepcopy(receipt)

    def refresh(self):
        """Recompute retention after an authoritative development re-evaluation."""
        self._members = self._retained(protected=self._protected_id)

    def update_node(self, node, fields):
        if type(fields) is not dict or not fields or not set(fields).issubset(MUTABLE_FIELDS):
            raise ValueError("population update violates node fields")
        updated = copy.deepcopy(self._node(node))
        for key, value in fields.items():
            setattr(updated, key, copy.deepcopy(value))
        nodes = {**self.nodes, node: updated}
        members = self._retained(nodes=nodes, protected=self._protected_id)
        self.nodes[node], self._members = updated, members

    def prune(self, node, reason):
        """Explicit safety exclusion affects this node only, never its children."""
        target = self._node(node)
        if node == self._protected_id:
            raise ValueError("cannot prune the driver-selected incumbent")
        if type(reason) is not str or not reason.strip():
            raise ValueError("population exclusion requires a reason")
        target.status, target.prune_reason = "pruned", reason
        self.refresh()
        self._emit("population_pruned", {"candidate_id": node, "reason": reason, "cascade": [node],
                                         "hard_deleted": False, "members": list(self.member_ids)})
        return [node]

    def _eligible(self, scope=None):
        return [node for node in super()._eligible(scope) if node.id in self._members and self._valid_parent(node)]

    def _ranked(self, scope=None):
        return sorted(self._eligible(scope), key=self._rank_key)

    def eligible_parent_ids(self):
        return tuple(sorted(node.id for node in self._eligible()))

    def _allowed(self, allowed_ids):
        if allowed_ids is None:
            return self._eligible()
        if not isinstance(allowed_ids, (list, tuple, set, frozenset)) or any(
                type(item) is not str or item not in self.nodes for item in allowed_ids):
            raise ValueError("sampling authority references an unknown candidate")
        allowed = set(allowed_ids)
        return [node for node in self._eligible() if node.id in allowed]

    def _sample_plan(self, eligible, k, strategy, state):
        if type(k) is not int or k < 0 or type(strategy) is not str or strategy not in _SELECTIONS:
            raise ValueError("invalid population sample size or strategy")
        if not eligible or k == 0:
            return [], dict(state), None
        before = dict(state)
        after = dict(state)
        pool = sorted(eligible, key=lambda node: node.id)
        selected = []
        def draw():
            value = int.from_bytes(hashlib.sha256(
                f"population-v1\0{self.sample_seed}\0{after['counter']}".encode()).digest(), "big")
            after["counter"] += 1
            return value
        def randbelow(size):
            ceiling = (1 << 256) - ((1 << 256) % size)
            while True:
                value = draw()
                if value < ceiling:
                    return value % size
        for _ in range(min(k, len(pool))):
            if strategy == "greedy":
                chosen = min(pool, key=self._rank_key)
            elif strategy == "uniform":
                chosen = pool[randbelow(len(pool))]
            elif strategy == "tournament":
                candidates, available = [], list(pool)
                for _ in range(min(self.tournament_size, len(available))):
                    candidates.append(available.pop(randbelow(len(available))))
                chosen = min(candidates, key=self._rank_key)
            else:
                values = [node.score if self.direction == "maximize" else -node.score for node in pool]
                maximum = max(values)
                weights = [math.exp((value - maximum) / self.temperature) for value in values]
                target, cumulative = ((draw() >> 203) / (1 << 53)) * sum(weights), 0.0
                chosen = pool[-1]
                for node, weight in zip(pool, weights):
                    cumulative += weight
                    if target < cumulative:
                        chosen = node
                        break
            selected.append(chosen.id)
            pool.remove(chosen)
        after["calls"] += 1
        receipt = {"schema_version": 1, "config_ref": _digest(self._config()),
                   "eligible": [{"id": node.id, "score": node.score, "attempt": node.attempt}
                                for node in sorted(eligible, key=lambda node: node.id)],
                   "k": k, "strategy": strategy, "before": before, "after": after, "selected": selected}
        receipt["receipt_ref"] = "sha256:" + _digest(receipt)
        return selected, after, receipt

    def sample(self, k, strategy=None):
        strategy = self.selection if strategy is None else strategy
        selected, after, receipt = self._sample_plan(self._eligible(), k, strategy, self._rng)
        if receipt is not None:
            self._emit("population_sample", receipt)
            self._rng = after
            self._sampling_receipts.append(copy.deepcopy(receipt))
        return selected

    def commit_sampling(self, receipts, *, allowed_ids=None):
        """Recompute a detached policy view's draws; never adopt its whole state."""
        if type(receipts) is not list:
            raise ValueError("sampling receipts must be a list")
        eligible, state, accepted = self._allowed(allowed_ids), dict(self._rng), []
        for supplied in receipts:
            if type(supplied) is not dict:
                raise ValueError("invalid population sampling receipt")
            _, state, actual = self._sample_plan(eligible, supplied.get("k"), supplied.get("strategy"), state)
            if actual is None or supplied != actual:
                raise ValueError("sampling receipt differs from authoritative members, parameters or RNG")
            accepted.append(actual)
        if accepted:
            self._emit("population_sampling_committed", {"receipts": accepted, "rng_state": state})
            self._rng = state
            self._sampling_receipts.extend(copy.deepcopy(accepted))
        return copy.deepcopy(accepted)

    def commit_selection(self, selected_ids, receipts, *, allowed_ids=None):
        """Commit only if M1 returned the final draw, before any RNG mutation."""
        if type(selected_ids) is not list or len(selected_ids) > 2 \
                or any(type(identifier) is not str for identifier in selected_ids) \
                or len(set(selected_ids)) != len(selected_ids) or type(receipts) is not list:
            raise ValueError("population selection must contain at most two distinct sampled parents")
        if selected_ids:
            if not receipts or type(receipts[-1]) is not dict or receipts[-1].get("selected") != selected_ids:
                raise ValueError("selected parents differ from the final sampling receipt")
        elif receipts:
            raise ValueError("empty selection cannot advance a hidden sampling transcript")
        return self.commit_sampling(receipts, allowed_ids=allowed_ids)

    def view(self, projection):
        if projection == "json":
            payload = json.loads(super().view(projection))
            payload["population"] = {"members": list(self.member_ids), "capacity": self.capacity,
                                     "protected_id": self._protected_id, "selection": self.selection}
            return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        return super().view(projection)

    def checkpoint(self):
        payload = {"config": {**self._config(), "structure": "population"},
            "git_state": self.git_state, "messages": self.messages,
            "inflight_executor": sorted(node.id for node in self.nodes.values() if node.status == "running"),
            "nodes": [asdict(self.nodes[key]) for key in sorted(self.nodes)], "edges": self._edge_payload(),
            "population": {"members": list(self.member_ids), "protected_id": self._protected_id,
                "outcomes": [{"candidate_id": key, **value} for key, value in self._outcomes.items()],
                "rng_state": dict(self._rng)}}
        checkpoint = FrontierCheckpoint(1, payload, _digest(payload))
        self._emit("frontier_checkpoint", {"payload_sha256": checkpoint.payload_sha256,
                                           "nodes": len(self.nodes), "inflight": len(payload["inflight_executor"])})
        return checkpoint.to_bytes()

    @classmethod
    def restore(cls, raw, store=None):
        checkpoint = FrontierCheckpoint.from_bytes(raw)
        payload = copy.deepcopy(checkpoint.payload)
        if set(payload) != {"config", "git_state", "messages", "inflight_executor", "nodes", "edges", "population"} \
                or payload["config"].get("structure") != "population":
            raise ValueError("checkpoint is not a population frontier")
        config = dict(payload["config"])
        del config["structure"]
        population_options(config)
        frontier = cls(**config, git_state=payload["git_state"], messages=payload["messages"], store=None)
        population = payload.pop("population")
        if type(population) is not dict or set(population) != {"members", "protected_id", "outcomes", "rng_state"}:
            raise ValueError("invalid population checkpoint fields")
        payload["config"] = {"metric": frontier.metric, "direction": frontier.direction,
                             "sample_seed": frontier.sample_seed, "structure": "tree"}
        base = ResearchFrontier.restore(FrontierCheckpoint(1, payload, _digest(payload)).to_bytes())
        frontier.nodes, frontier.edges = base.nodes, base.edges
        for node in frontier.nodes.values():
            if type(node.id) is not str or not node.id or type(node.created_cycle) is not int or node.created_cycle < 0 \
                    or len(node.parent_ids) > 2 or len(set(node.parent_ids)) != len(node.parent_ids) \
                    or node.children_ids != sorted(child for parent, child in frontier.edges["skeleton"] if parent == node.id):
                raise ValueError("population checkpoint lineage is inconsistent")
            if node.score is not None and (type(node.score) not in (int, float) or not math.isfinite(node.score)):
                raise ValueError("population checkpoint score must be finite")
        if type(population["outcomes"]) is not list:
            raise ValueError("population outcomes must be ordered")
        selected = None
        for outcome in population["outcomes"]:
            if type(outcome) is not dict or set(outcome) != {"candidate_id", "admitted", "reason", "selected_id", "decision_ref"}:
                raise ValueError("invalid population outcome")
            identifier = outcome["candidate_id"]
            if identifier not in frontier.nodes or identifier in frontier._outcomes or type(outcome["admitted"]) is not bool \
                    or any(type(outcome[key]) is not str or not outcome[key].strip() for key in ("reason", "decision_ref")):
                raise ValueError("population outcome identity or authority is invalid")
            selected = identifier if outcome["admitted"] else selected
            if outcome["selected_id"] != selected:
                raise ValueError("population selected history differs from M9 outcomes")
            frontier._outcomes[identifier] = {key: value for key, value in outcome.items() if key != "candidate_id"}
        if population["protected_id"] != selected:
            raise ValueError("population protected incumbent differs from final M9 selection")
        frontier._protected_id = selected
        expected = frontier._retained(protected=selected)
        if type(population["members"]) is not list or population["members"] != sorted(expected):
            raise ValueError("population members differ from deterministic retention")
        state = population["rng_state"]
        if type(state) is not dict or set(state) != {"counter", "calls"} \
                or any(type(value) is not int or value < 0 for value in state.values()):
            raise ValueError("invalid population RNG state")
        frontier._members, frontier._rng = expected, dict(state)
        frontier.store = store
        frontier._emit("frontier_restored", {"payload_sha256": checkpoint.payload_sha256,
                                           "nodes": len(frontier.nodes)})
        return frontier
