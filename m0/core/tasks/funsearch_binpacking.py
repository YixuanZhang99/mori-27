"""Content-bound OR3 partitions."""
import hashlib
import json


def split_instances(instances):
    if type(instances) is not dict or len(instances) != 20 or any(
            type(key) is not str or not key.strip() for key in instances):
        raise ValueError('OR3 requires exactly 20 named instances')
    for value in instances.values():
        if (type(value) is not dict or set(value) != {'capacity', 'num_items', 'items'} or
                type(value['capacity']) is not int or value['capacity'] <= 0 or
                type(value['num_items']) is not int or type(value['items']) is not list or
                value['num_items'] < 1 or len(value['items']) != value['num_items'] or any(
                    type(item) is not int or not 0 < item <= value['capacity'] for item in value['items'])):
            raise ValueError('invalid OR3 instance')
    names = sorted(instances)
    output = {}
    for label, keys in (('dev', names[:10]), ('held_out', names[10:])):
        payload = {key: instances[key] for key in keys}
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        output[label] = {'instances': json.loads(canonical), 'sha256': hashlib.sha256(canonical).hexdigest()}
    return output
