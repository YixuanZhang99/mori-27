"""METR RE-Bench adapter pinned to the deprecated official repository snapshot."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
from pathlib import Path
from typing import Literal

import yaml

from core.tasks.adapter import (ArtifactRef, EvalContract, FidelityLevel,
                                ProvenanceDoc, Workspace)
from core.tasks.benchmark import (ScoreRunRecord, SelectionCandidate,
                                  SelectionContract, SelectionReceipt)
from core.x1.store import AppendOnlyStore

REVISION = "a0cc6d4a91b20f84ebef505d5c72358f88b3b389"
TASK_LIST_SHA256 = "0f6205a46c61a26e7476e498a4199b7d2a3ee4abf53c27dbb7f3640ddcd008ff"
SOURCE = "https://github.com/METR/RE-Bench"
ASSETS = Path(__file__).resolve().parent / "assets"
TASK_IDS = ("ai_rd_fix_embedding", "ai_rd_nanogpt_chat_rl",
            "ai_rd_optimize_llm_foundry", "ai_rd_restricted_mlm",
            "ai_rd_rust_codecontests_inference", "ai_rd_small_scaling_law",
            "ai_rd_triton_cumsum")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class REBenchAdapter:
    name = "re_bench"

    def __init__(self, task_id: str, official_root: str | Path,
                 manifest_path: str | Path | None = None):
        self.task_id = task_id
        self.official_root = Path(official_root).resolve()
        self.manifest_path = Path(manifest_path or ASSETS / "snapshot_manifest.json")
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("revision") != REVISION:
            raise ValueError("official RE-Bench snapshot revision mismatch")
        if task_id not in TASK_IDS:
            raise ValueError("task is not in the locked seven-family RE-Bench suite")
        self.verify_protected()

    @staticmethod
    def task_ids() -> list[str]:
        if sha256(ASSETS / "suite_manifest.yaml") != TASK_LIST_SHA256:
            raise ValueError("locked RE-Bench suite manifest hash mismatch")
        return list(TASK_IDS)

    def verify_protected(self) -> None:
        official_suite = self.official_root / "suite_manifest.yaml"
        if not official_suite.is_file() \
                or official_suite.read_bytes() != (ASSETS / "suite_manifest.yaml").read_bytes():
            raise ValueError("official RE-Bench suite differs from the locked snapshot")
        for rel, expected in self.manifest.get("files", {}).items():
            if rel != "suite_manifest.yaml" and not rel.startswith(f"{self.task_id}/"):
                continue
            path = self.official_root / rel
            if not path.is_file() or sha256(path) != expected:
                raise ValueError(f"protected official file missing or modified: {rel}")

    def _task_manifest(self) -> dict:
        path = self.official_root / self.task_id / "manifest.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("tasks", {}).get("main"), dict):
            raise ValueError("official RE-Bench main task manifest is invalid")
        return payload

    def score_on_usage_limits(self) -> bool:
        scoring = self._task_manifest()["tasks"]["main"].get("scoring", {})
        return scoring.get("score_on_usage_limits") is True

    def setup(self, workspace: Workspace) -> None:
        """Create run metadata only; Vivaria owns the actual task environment."""
        self.verify_protected()
        root = workspace.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        readme = self.official_root / self.task_id / "README.md"
        (root / "description.md").write_bytes(readme.read_bytes())
        (root / "task.json").write_text(json.dumps({
            "benchmark": self.name, "task_id": f"{self.task_id}/main",
            "official_revision": REVISION, "task_list_sha256": TASK_LIST_SHA256,
            "runner": "Vivaria", "score_log_visibility": "run_level_audit"},
            indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        if workspace.evidence is not None:
            workspace.evidence.append("benchmark_workspace_setup", {
                "benchmark": self.name, "task_id": self.task_id,
                "official_revision": REVISION, "task_list_sha256": TASK_LIST_SHA256,
                "visible_files": ["description.md", "task.json"],
                "solution_files_exposed": False})

    def eval_contract(self) -> EvalContract:
        protected = tuple(rel for rel in self.manifest["files"]
                          if rel == "suite_manifest.yaml" or rel.startswith(f"{self.task_id}/"))
        return EvalContract(
            metric_direction="maximize", eval_cmd="viv score",
            fidelity_levels=(
                FidelityLevel("dev", {"wallclock": 0}, 1, "exploration"),
                FidelityLevel("audit", {"eval_count": 1}, 1, "audit")),
            required_outputs=(), protected_paths=protected, visibility="audit")

    def initial_artifact(self) -> ArtifactRef:
        readme = self.official_root / self.task_id / "README.md"
        return ArtifactRef(uri=f"official+file://{readme}", sha256=sha256(readme))

    def provenance(self) -> ProvenanceDoc:
        return ProvenanceDoc(
            source_uri=SOURCE, revision=REVISION,
            protocol_uri=f"{SOURCE}/tree/{REVISION}/setup#starting-an-agent-run",
            task_list_sha256=TASK_LIST_SHA256,
            license="MIT; upstream requests reasonable protection of benchmark solutions",
            notes={"maintenance": "upstream marks RE-Bench tasks deprecated",
                   "task_count": "7", "official_runner": "Vivaria",
                   "score_visibility": "raw score logs and aggregate scores stay in run-level audit"})

    def _official_aggregate(self, score_log: list[dict]) -> float:
        path = self.official_root / self.task_id / f"{self.task_id}.py"
        spec = importlib.util.spec_from_file_location(f"_re_bench_{self.task_id}", path)
        if spec is None or spec.loader is None:
            raise ValueError("cannot load official RE-Bench task family")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        task = module.TaskFamily.get_tasks()["main"]
        return module.TaskFamily.aggregate_scores(task, score_log)

    def grade_score_log(self, score_log_path: str | Path, audit_store: AppendOnlyStore,
                        aggregator=None) -> dict:
        """Aggregate a real Vivaria score log with official code, in the audit lane."""
        self.verify_protected()
        path = Path(score_log_path).resolve()
        score_log = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(score_log, list) or not score_log \
                or not all(isinstance(entry, dict) for entry in score_log):
            raise ValueError("official RE-Bench score log must be a non-empty object list")
        score = (aggregator or self._official_aggregate)(score_log)
        valid = (not isinstance(score, bool) and isinstance(score, (int, float))
                 and math.isfinite(score))
        report = {"benchmark": self.name, "task_id": self.task_id,
                  "official_revision": REVISION, "official_aggregate_scores": True,
                  "score": score if valid else None,
                  "invalid_score": None if valid else str(score),
                  "score_log_sha256": sha256(path),
                  "score_on_usage_limits": self.score_on_usage_limits()}
        audit_store.append("official_scoring_report", report)
        if not valid:
            raise ValueError("official RE-Bench aggregate score is not finite")
        return report

    @staticmethod
    def public_report(report: dict, visibility: str = "dev") -> dict:
        if report.get("benchmark") != "re_bench" or not report.get("official_aggregate_scores"):
            raise ValueError("official RE-Bench scoring report is required")
        if visibility == "dev":
            return {"task_id": report["task_id"], "scoring_recorded": True}
        if visibility == "audit":
            return {"task_id": report["task_id"], "audit/score": report["score"]}
        raise ValueError("unknown RE-Bench report visibility")

    def measured_run_record(self, report: dict, seed: int,
                            arm: Literal["host", "governed"], backbone: str,
                            budget: dict[str, float], actual_costs: dict[str, float],
                            evidence_refs: tuple[str, ...], timed_out: bool = False,
                            selection: SelectionContract | None = None,
                            selection_receipt: SelectionReceipt | None = None) -> ScoreRunRecord:
        if report.get("benchmark") != self.name or report.get("task_id") != self.task_id \
                or not report.get("official_aggregate_scores") or not evidence_refs:
            raise ValueError("official RE-Bench report and scoring evidence refs are required")
        selection = selection or SelectionContract(
            "single_run", "vivaria-official-aggregate-v1", "not_applicable")
        if selection_receipt is None and selection.selection_object == "single_run":
            candidate_id = f"{arm}:{self.task_id}:{seed}:final"
            selection_receipt = SelectionReceipt(
                selection, (SelectionCandidate(candidate_id, evidence_refs[0]),), candidate_id)
        return ScoreRunRecord(
            benchmark=self.name, task_list_sha256=TASK_LIST_SHA256,
            task_id=self.task_id, seed=seed, arm=arm, backbone=backbone,
            budget=budget, actual_costs=actual_costs, score=report["score"],
            metric_direction="maximize", timed_out=timed_out,
            evidence_refs=evidence_refs, measured=True,
            selection=selection, selection_receipt=selection_receipt)
