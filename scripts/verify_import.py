#!/usr/bin/env python3
"""Verify original handoff bytes; new repository documentation is out of scope."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="Verify a Git snapshot instead of the current working files")
    args = parser.parse_args()
    archive = None
    revision = None
    if args.ref:
        revision = subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", args.ref + "^{commit}"],
            cwd=root, text=True).strip()
        payload = subprocess.check_output(["git", "archive", "--format=tar", revision], cwd=root)
        archive = tarfile.open(fileobj=io.BytesIO(payload))

    def read(relative: str) -> bytes:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Unsafe path: {relative}")
        if archive is not None:
            member = archive.getmember(relative)
            if not member.isfile():
                raise ValueError(f"Not a regular archived file: {relative}")
            stream = archive.extractfile(member)
            assert stream is not None
            return stream.read()
        return path.read_bytes()

    manifest = json.loads(read("MANIFEST.json"))
    audit = json.loads(read("docs/review/import-audit.json"))
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
        try:
            payload = read(mapping.get(original, original))
        except (OSError, KeyError, ValueError):
            errors.append(f"Missing or unsafe path: {original}")
            continue
        if len(payload) != entry["size_bytes"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            errors.append(f"Content differs from handoff: {original}")
        checked += 1
    if archive is not None:
        archive.close()
    print(json.dumps({"git_revision": revision,
                      "checked_payload_files": checked,
                      "excluded_embedded_git_files": len(excluded),
                      "errors": errors, "passed": not errors},
                     ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
