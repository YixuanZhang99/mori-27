"""Classic-system profiles compiled to M0 configuration (no kernel edits)."""
from __future__ import annotations

import json
from pathlib import Path

from core.extensions import H2MonitorExtension, NoveltyGateExtension

PROFILE_DIR = Path(__file__).resolve().parents[1] / "config" / "profiles"


def load_profile(name: str) -> dict:
    path = PROFILE_DIR / f"{name}.json"
    with path.open(encoding="utf-8") as f:
        profile = json.load(f)
    if "schema_version" in profile:
        from core.composition.contracts import AssemblyConfig
        return AssemblyConfig.from_dict(profile).to_dict()
    required = {"name", "operators", "parent_pool", "extensions"}
    missing = required - profile.keys()
    if missing:
        raise ValueError(f"profile {name} missing keys: {sorted(missing)}")
    if profile["operators"].get("improve") not in {"llm_reflective", "llm_evolve_block"}:
        raise ValueError(f"unsupported M0 improve implementation in {name}")
    return profile


def extensions_for(profile: dict) -> list:
    result = []
    for spec in profile["extensions"]:
        kind = spec["type"]
        if kind == "novelty_gate":
            result.append(NoveltyGateExtension(threshold=spec.get("threshold", 0.95)))
        elif kind == "h2_monitor":
            result.append(H2MonitorExtension(window=spec.get("window", 5)))
        else:
            raise ValueError(f"unknown extension type: {kind}")
    return result
