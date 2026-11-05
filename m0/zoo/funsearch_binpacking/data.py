"""Content-bound OR3 dev/held-out files produced by the existing preparation tool."""
import hashlib
import json
from pathlib import Path
import re

from core.tasks.funsearch_binpacking import split_instances

SPLIT_RULE = 'sorted instance id: first 10 dev, last 10 held_out'


def _read(path, expected=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError('frozen OR3 file is unavailable')
    raw = path.read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('frozen OR3 file content changed')
    return raw


class FrozenOR3:
    @classmethod
    def from_manifest(cls, path):
        path = Path(path).absolute()
        raw = _read(path)
        manifest = json.loads(raw)
        if (type(manifest) is not dict or set(manifest) != {
                'schema_version', 'notebook_sha256', 'split_rule', 'splits'} or
                type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or
                type(manifest['notebook_sha256']) is not str or
                not re.fullmatch(r'[0-9a-f]{64}', manifest['notebook_sha256']) or
                manifest['split_rule'] != SPLIT_RULE or type(manifest['splits']) is not dict or
                set(manifest['splits']) != {'dev', 'held_out'}):
            raise ValueError('invalid frozen OR3 manifest')
        instance = cls()
        instance.paths, instance.hashes = {}, {}
        instance._files = {path: hashlib.sha256(raw).hexdigest()}
        instance.notebook_sha256 = manifest['notebook_sha256']
        values = {}
        for split, metadata in manifest['splits'].items():
            if (type(metadata) is not dict or set(metadata) != {'sha256', 'count'} or
                    type(metadata['count']) is not int or metadata['count'] != 10 or
                    type(metadata['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}', metadata['sha256'])):
                raise ValueError('OR3 requires ten frozen cases per partition')
            file = path.parent / split / 'data.json'
            values[split] = json.loads(_read(file, metadata['sha256']))
            if type(values[split]) is not dict or len(values[split]) != 10:
                raise ValueError('OR3 requires ten named cases per partition')
            instance.paths[split], instance.hashes[split] = file, metadata['sha256']
            instance._files[file] = metadata['sha256']
        if set(values['dev']) & set(values['held_out']):
            raise ValueError('OR3 dev and held-out case IDs must be disjoint')
        partitions = split_instances({**values['dev'], **values['held_out']})
        if any(set(partitions[key]['instances']) != set(values[key]) for key in values):
            raise ValueError('OR3 partitions differ from the frozen sorted-ID split')
        instance.identity = 'sha256:' + instance._files[path]
        instance.split_hashes = {key: 'sha256:' + value for key, value in instance.hashes.items()}
        return instance

    def validate(self):
        for path, digest in self._files.items():
            _read(path, digest)

    def rows(self, split):
        self.validate()
        return json.loads(_read(self.paths[split], self.hashes[split]))

    def ids(self, split):
        return sorted(self.rows(split))
