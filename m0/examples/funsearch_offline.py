"""Offline FunSearch-shaped run: frozen skeleton + evolve-block + two islands."""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.archive import IslandArchive
from core.loop import Framework, LoopConfig
from examples.toy_gepa import toy_evaluator


class FunSearchProposer:
    def __init__(self):
        self.last_usage = {"total_tokens": 0}

    def __call__(self, prompt: str) -> str:
        self.last_usage = {"total_tokens": 12}
        if prompt.startswith("[draft"):
            return "<EVOLVE-BLOCK>\nSolve the problem carefully.\n</EVOLVE-BLOCK>"
        parent = prompt.split("FROZEN SKELETON AND EDITABLE BLOCK:\n", 1)[1].split(
            "\n\nSCORE:", 1)[0]
        block = parent.split("<EVOLVE-BLOCK>", 1)[1].split("</EVOLVE-BLOCK>", 1)[0].strip()
        match = re.search(r"missing hint: (\w+)", prompt)
        return block + ("\n" + match.group(1) if match else "")


def run(workdir: str = "/tmp/m0_funsearch", generations: int = 10) -> dict:
    fw = Framework(FunSearchProposer(), toy_evaluator,
                   LoopConfig(max_generations=generations), workdir,
                   archive=IslandArchive(num_islands=2, migration_interval=2),
                   improve_impl="llm_evolve_block", profile_name="funsearch_offline")
    return fw.evolve("FunSearch-shaped offline evolution")


if __name__ == "__main__":
    out = run(workdir=tempfile.mkdtemp(prefix="m0_funsearch_"))
    print("best_score:", out["best_score"])
    print("main_scores:", [round(s, 2) for s in out["main_scores"]])
    print("C1/C2 audit =", out["governance_audit"]["passed"])
    print("archive:", out["archive_health"])
