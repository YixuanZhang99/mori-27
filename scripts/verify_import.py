#!/usr/bin/env python3
"""Verify original handoff bytes; new repository documentation is out of scope."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    audit = json.loads((root / "docs/review/import-audit.json").read_text(encoding="utf-8"))
    excluded = {item["path"] for item in audit["excluded_git_metadata"]}
    mapping = audit["path_mapping"]
    errors: list[str] = []
    checked = 0
    for entry in manifest["files"]:
        original = entry["path"]
        if original in excluded:
            if not original.startswith("m0/vendor/openevolve/.git/"):
                errors.append(f"Unexpected exclusion: {original}")
            continue
        path = (root / mapping.get(original, original)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            errors.append(f"Missing or unsafe path: {original}")
            continue
        payload = path.read_bytes()
        if len(payload) != entry["size_bytes"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            errors.append(f"Content differs from handoff: {original}")
        checked += 1
    print(json.dumps({"checked_payload_files": checked,
                      "excluded_embedded_git_files": len(excluded),
                      "errors": errors, "passed": not errors},
                     ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
