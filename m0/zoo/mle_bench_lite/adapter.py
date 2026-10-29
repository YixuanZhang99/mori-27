"""OpenAI MLE-Bench Lite adapter pinned to an official repository snapshot."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from core.tasks.adapter import (ArtifactRef, EvalContract, FidelityLevel,
                                ProvenanceDoc, Workspace)
from core.tasks.benchmark import (BenchmarkRunRecord, SelectionCandidate,
                                  SelectionContract, SelectionReceipt)
from core.x1.store import AppendOnlyStore

REVISION = "507f92e1138bb6e40dac5c6ee7a6758e6424bf97"
TASK_LIST_SHA256 = "590270f007fa96b4060f59f3861500159c73ca50f7f30ff6bd38303c236c799b"
SOURCE = "https://github.com/openai/mle-bench"
ASSETS = Path(__file__).resolve().parent / "assets"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MLEBenchLiteAdapter:
    name = "mle_bench_lite"

    def __init__(self, competition_id: str, official_root: str | Path,
                 data_root: str | Path, manifest_path: str | Path | None = None):
        self.competition_id = competition_id
        self.official_root = Path(official_root).resolve()
        self.data_root = Path(data_root).resolve()
        self.manifest_path = Path(manifest_path or ASSETS / "snapshot_manifest.json")
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if self.manifest["revision"] != REVISION:
            raise ValueError("official snapshot revision mismatch")
        if competition_id not in self.task_ids():
            raise ValueError("competition is not in the locked 22-task Lite split")
        self.verify_protected()

    @staticmethod
    def task_ids() -> list[str]:
        path = ASSETS / "low.txt"
        if sha256(path) != TASK_LIST_SHA256:
            raise ValueError("locked Lite task-list hash mismatch")
        return path.read_text(encoding="utf-8").splitlines()

    def _task_rel(self, filename: str) -> str:
        return f"mlebench/competitions/{self.competition_id}/{filename}"

    def verify_protected(self) -> None:
        official_split = self.official_root / "experiments/splits/low.txt"
        if not official_split.exists() or official_split.read_bytes() != (ASSETS / "low.txt").read_bytes():
            raise ValueError("official Lite split differs from the locked snapshot")
        for filename in ("config.yaml", "grade.py", "checksums.yaml",
                         "leaderboard.csv", "description.md"):
            rel = self._task_rel(filename)
            path = self.official_root / rel
            if not path.is_file() or sha256(path) != self.manifest["files"].get(rel):
                raise ValueError(f"protected official file missing or modified: {rel}")

    def setup(self, workspace: Workspace, include_data: bool = False) -> None:
        """Expose task inputs only; never copy grader, answers or leaderboard.

        Production agents need prepared public train/test inputs under ``data/``.
        The default retains the minimal protocol-fixture workspace.
        """
        self.verify_protected()
        sample = self.data_root / self.competition_id / "prepared/public/sample_submission.csv"
        if not sample.is_file():
            raise FileNotFoundError("run `mlebench prepare -c <id>` before workspace setup")
        root = workspace.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.official_root / self._task_rel("description.md"),
                        root / "description.md")
        shutil.copyfile(sample, root / "sample_submission.csv")
        visible_files = ["description.md", "sample_submission.csv", "task.json"]
        if include_data:
            shutil.copytree(sample.parent, root / "data", dirs_exist_ok=True)
            visible_files.append("data/")
        (root / "task.json").write_text(json.dumps({
            "benchmark": self.name, "competition_id": self.competition_id,
            "official_revision": REVISION, "task_list_sha256": TASK_LIST_SHA256,
            "required_output": "submission.csv"}, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        if workspace.evidence is not None:
            workspace.evidence.append("benchmark_workspace_setup", {
                "benchmark": self.name, "competition_id": self.competition_id,
                "official_revision": REVISION, "task_list_sha256": TASK_LIST_SHA256,
                "visible_files": visible_files,
                "sample_submission_sha256": sha256(sample)})

    def eval_contract(self) -> EvalContract:
        leaderboard = self.official_root / self._task_rel("leaderboard.csv")
        with leaderboard.open(newline="", encoding="utf-8") as f:
            scores = [float(row["score"]) for row in csv.DictReader(f)]
        if len(scores) < 2 or scores[0] == scores[-1]:
            raise ValueError("leaderboard cannot establish metric direction")
        protected = tuple(self._task_rel(name) for name in
                          ("config.yaml", "grade.py", "checksums.yaml", "leaderboard.csv"))
        return EvalContract(
            metric_direction="minimize" if scores[0] < scores[-1] else "maximize",
            eval_cmd=(f"mlebench grade-sample {{cwd}}/submission.csv "
                      f"{self.competition_id} --data-dir {{data_dir}}"),
            fidelity_levels=(
                FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),
                FidelityLevel("admission", {"eval_count": 1}, 1, "admission"),
                FidelityLevel("audit", {"eval_count": 1}, 1, "audit")),
            required_outputs=("submission.csv",), protected_paths=protected,
            visibility="dev")

    def initial_artifact(self) -> ArtifactRef:
        sample = self.data_root / self.competition_id / "prepared/public/sample_submission.csv"
        return ArtifactRef(uri=f"official+file://{sample}",
                           sha256=sha256(sample) if sample.is_file() else "")

    def provenance(self) -> ProvenanceDoc:
        return ProvenanceDoc(
            source_uri=SOURCE, revision=REVISION,
            protocol_uri=f"{SOURCE}/tree/{REVISION}#benchmarking",
            task_list_sha256=TASK_LIST_SHA256, license="MIT (benchmark code); task data terms vary",
            notes={"split": "experiments/splits/low.txt (22 competitions)",
                   "leaderboard_status": "new public submissions paused upstream since 2026-04-24"})

    def public_report(self, report: dict, visibility: str = "dev") -> dict:
        """Defense-in-depth redaction between official grading and search feedback."""
        if report.get("competition_id") != self.competition_id:
            raise ValueError("grading report competition mismatch")
        valid = bool(report.get("valid_submission"))
        if visibility == "dev":
            return {"competition_id": self.competition_id, "valid_submission": valid}
        if visibility == "admission":
            return {"competition_id": self.competition_id, "valid_submission": valid,
                    "admission/above_median": bool(report.get("above_median"))}
        if visibility == "audit":
            return {"competition_id": self.competition_id, "valid_submission": valid,
                    "audit/score": report.get("score"),
                    "audit/any_medal": bool(report.get("any_medal")),
                    "audit/above_median": bool(report.get("above_median")),
                    "audit/gold_medal": bool(report.get("gold_medal")),
                    "audit/silver_medal": bool(report.get("silver_medal")),
                    "audit/bronze_medal": bool(report.get("bronze_medal"))}
        raise ValueError("unknown report visibility")

    def grade_submission(self, workspace: Workspace, visibility: str,
                         audit_store: AppendOnlyStore, grader=None) -> dict:
        """Run official grading on demand; raw reports stay in the audit lane.

        The optional grader is an offline protocol-test injection. Production
        callers omit it, which imports and executes the pinned official package.
        """
        if visibility not in {"dev", "admission", "audit"}:
            raise ValueError("unknown report visibility")
        self.verify_protected()
        submission = workspace.root.resolve() / "submission.csv"
        if not submission.is_file():
            raise FileNotFoundError("required output submission.csv is missing")
        if grader is None:
            from mlebench.grade import grade_csv
            from mlebench.registry import Registry
            competition = Registry(self.data_root).get_competition(self.competition_id)
            grader = lambda path: grade_csv(path, competition)
        report = grader(submission)
        if hasattr(report, "to_dict"):
            report = report.to_dict()
        if not isinstance(report, dict):
            raise ValueError("official grader must return a report mapping")
        digest = hashlib.sha256(json.dumps(report, sort_keys=True, default=str).encode()).hexdigest()
        audit_store.append("official_grading_report", {
            "benchmark": self.name, "official_revision": REVISION,
            "competition_id": self.competition_id, "report_sha256": digest,
            "report": report})
        return self.public_report(report, visibility)

    def measured_run_record(self, report: dict, seed: int,
                            arm: Literal["host", "governed"], backbone: str,
                            budget: dict[str, float], actual_costs: dict[str, float],
                            evidence_refs: tuple[str, ...],
                            selection: SelectionContract | None = None,
                            selection_receipt: SelectionReceipt | None = None) -> BenchmarkRunRecord:
        """Convert an actual official report into the paired-comparison schema."""
        if report.get("competition_id") != self.competition_id or not evidence_refs:
            raise ValueError("official report and grading evidence refs are required")
        selection = selection or SelectionContract(
            "single_run", "mle-official-final-submission-v1", "not_applicable")
        if selection_receipt is None and selection.selection_object == "single_run":
            candidate_id = f"{arm}:{self.competition_id}:{seed}:final"
            selection_receipt = SelectionReceipt(
                selection, (SelectionCandidate(candidate_id, evidence_refs[0]),), candidate_id)
        return BenchmarkRunRecord(
            benchmark=self.name, task_list_sha256=TASK_LIST_SHA256,
            task_id=self.competition_id, seed=seed, arm=arm, backbone=backbone,
            budget=budget, actual_costs=actual_costs,
            valid_submission=bool(report.get("valid_submission")),
            any_medal=bool(report.get("any_medal")),
            above_median=bool(report.get("above_median")),
            evidence_refs=evidence_refs, measured=True,
            selection=selection, selection_receipt=selection_receipt)
