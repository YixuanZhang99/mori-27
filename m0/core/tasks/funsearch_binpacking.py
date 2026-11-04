"""Content-bound OR3 partitions."""
import hashlib
import json


def score_partition(instances, priority):
    """Score a complete partition; caller must sandbox the supplied priority."""
    if type(instances) is not dict or len(instances) != 10 or any(
            type(key) is not str or not key.strip() for key in instances):
        raise ValueError('OR3 partition requires 10 named instances')
    scores = {key: score_instance(instances[key], priority) for key in sorted(instances)}
    return {'case_scores': scores, 'mean_score': sum(scores.values()) / len(scores)}


def score_instance(instance, priority):
    """Return negative used-bin count; execute priority only in a caller's sandbox."""
    import numpy as np
    if (not callable(priority) or type(instance) is not dict or
            set(instance) != {'capacity', 'num_items', 'items'} or
            type(instance['capacity']) is not int or instance['capacity'] <= 0 or
            type(instance['num_items']) is not int or type(instance['items']) is not list or
            instance['num_items'] < 1 or len(instance['items']) != instance['num_items'] or any(
                type(item) is not int or not 0 < item <= instance['capacity'] for item in instance['items'])):
        raise ValueError('invalid OR3 instance or priority')
    bins = np.full(instance['num_items'], instance['capacity'], dtype=np.int64)
    for item in instance['items']:
        eligible = np.flatnonzero(bins >= item)
        scores = np.asarray(priority(item, bins[eligible].copy()))
        if (scores.shape != eligible.shape or scores.dtype.kind not in 'fiu' or
                not np.isfinite(scores).all()):
            raise ValueError('priority must return one finite numeric score per eligible bin')
        bins[eligible[int(np.argmax(scores))]] -= item
    return -int(np.count_nonzero(bins != instance['capacity']))


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
