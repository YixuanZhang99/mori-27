"""Isolated pre-import launcher for a frozen comparison on a trusted host."""
import hashlib
import json
from pathlib import Path
import runpy
import sys


def dependency_identity(paths):
    result = {}
    for root in sorted({Path(path).resolve() for path in paths}, key=str):
        if not root.is_dir():
            raise ValueError('comparison dependency root is missing')
        digestor = hashlib.sha256()
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError('comparison dependency roots cannot contain symlinks')
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('comparison dependency contains a non-regular file')
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            digestor.update(relative.encode() + b'\0sha256:' + file_hash.encode() + b'\0')
        result[str(root)] = digestor.hexdigest()
    return result


def main():
    expected = json.loads(sys.argv[1])
    source_root, _official_root, module = sys.argv[2:5]
    if not isinstance(expected, dict) or not expected or dependency_identity(expected) != expected:
        raise ValueError('comparison dependency identity changed')
    sys.path.extend([source_root, *sorted(expected)])
    sys.argv = [module, *sys.argv[5:]]
    runpy.run_module(module, run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main()
