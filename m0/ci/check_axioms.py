#!/usr/bin/env python3
"""Dependency/axiom static gates. stdlib-only and safe for offline CI."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
FORBIDDEN_SYNC = {"time", "datetime", "urllib", "requests", "socket", "openai"}


def tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def has_forbidden_import(path: Path, extra=()) -> bool:
    denied = set(FORBIDDEN_SYNC).union(extra)
    return any(name.split(".")[0] in denied or name in denied
               for name in imports(path))


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def dependency_cycles() -> list[list[str]]:
    """Return one canonical cycle per cyclic strongly connected component."""
    graph = {}
    for path in CORE.rglob("*.py"):
        node = module_name(path)
        graph[node] = {name for name in imports(path)
                       if name.startswith("core.") and name != node}

    # Tarjan SCC avoids both entry-node false self-cycles and duplicate paths.
    index = 0
    indices, lowlinks, stack = {}, {}, []
    on_stack, components = set(), []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(graph[node]):
            if nxt not in graph:
                continue
            if nxt not in indices:
                visit(nxt)
                lowlinks[node] = min(lowlinks[node], lowlinks[nxt])
            elif nxt in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[nxt])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                components.append(sorted(component) + [min(component)])

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def check() -> tuple[dict[str, bool], dict]:
    checks, values = {}, {}
    policy_files = list((CORE / "policy").glob("*.py"))
    sync_files = policy_files + list((CORE / "budget").glob("*.py")) + [CORE / "eval/gate.py"]
    checks["T_channel"] = all(not has_forbidden_import(path, {"core.budget", "core.eval", "core.llm"})
                              for path in policy_files)
    checks["T_no_clock_network_llm"] = all(not has_forbidden_import(path) for path in sync_files)
    checks["T_no_policy_gate_import"] = all("core.eval" not in imports(path) for path in policy_files)

    gate_tree = tree(CORE / "eval/gate.py")
    gate_names = {node.id for node in ast.walk(gate_tree) if isinstance(node, ast.Name)}
    gate_names.update(node.name for node in ast.walk(gate_tree)
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    gate_attrs = {node.attr for node in ast.walk(gate_tree) if isinstance(node, ast.Attribute)}
    forbidden_gate_inputs = {"combined_score", "cost", "costs", "usd"}
    checks["T_gate_not_rank"] = not forbidden_gate_inputs.intersection(gate_names | gate_attrs)
    checks["T_stop_table"] = "STOP_ACTION_TABLE" in gate_names and "stop_action" in gate_names

    loop_tree = tree(CORE / "loop.py")
    framework = next(node for node in loop_tree.body
                     if isinstance(node, ast.ClassDef) and node.name == "Framework")
    public_instance = [node.name for node in framework.body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and not node.name.startswith("_") and node.name != "from_profile"]
    checks["A1_public_api"] = sorted(public_instance) == ["evolve", "inspect", "replay"]
    values["public_instance_api"] = public_instance

    store_tree = tree(CORE / "x1/store.py")
    store = next(node for node in store_tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "AppendOnlyStore")
    methods = {node.name for node in store.body if isinstance(node, ast.FunctionDef)}
    checks["S5_append_only"] = not methods.intersection({"update", "delete", "truncate"})

    cycles = dependency_cycles()
    checks["A5_no_dependency_cycles"] = not cycles
    values["dependency_cycles"] = cycles
    core_imports = {path: imports(path) for path in CORE.rglob("*.py")}
    checks["D10_benchmark_isolated"] = (
        not any("core.knowledge" in core_imports[CORE / name]
                for name in ("loop.py", "profiles.py"))
        and not any(any(name == "zoo" or name.startswith("zoo.") for name in names)
                    for names in core_imports.values())
        and not any("mle_bench" in path.read_text(encoding="utf-8")
                    for path in CORE.rglob("*.py")))

    context = (ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    required = {"AllocationIntent", "BudgetLedger", "Receipt", "ScopedMemory",
                "KnowledgeService", "EvaluatorMetaGate", "ExchangeRateTable",
                "CrossoverContract", "ParetoArchive", "TaskAdapter",
                "BenchmarkRunRecord", "SameBudgetComparison", "ExecutorSpec",
                "EvidenceRecord", "GitWorktreeExecutor", "HITLController",
                "ResearchFrontier", "FrontierCheckpoint", "RunCheckpoint",
                "resume_from_checkpoint", "stop_after_generation", "StateMutation",
                "StateApplier", "BestFirstPolicy", "promote_level", "ExecutorPool",
                "BatchScheduler", "AdmissionDecision", "CostVec", "actual_costs",
                "recovery_state", "BatchScheduler.resume", "batch_decision"}
    checks["A6_context_terms"] = all(term in context for term in required)

    knowledge_source = (CORE / "knowledge/types.py").read_text(encoding="utf-8")
    audit_line = next(line for line in knowledge_source.splitlines()
                      if line.startswith("AuditTier ="))
    checks["D2_no_audit_veto"] = "veto" not in audit_line
    return checks, values


def main() -> int:
    checks, values = check()
    result = {"command": "python3 ci/check_axioms.py", "checks": checks,
              "values": values, "exit_code": 0 if all(checks.values()) else 1}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
