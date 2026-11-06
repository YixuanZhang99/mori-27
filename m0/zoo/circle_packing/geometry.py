"""Validate untrusted, bounded geometry without trusting candidate metrics."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat

TARGET = 2.635
TOLERANCE = 1e-6
MAX_GEOMETRY_BYTES = 65536


def _number(value):
    if type(value) not in (int, float):
        raise ValueError('geometry values must be finite real numbers')
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError('geometry values must be finite real numbers') from error
    if not math.isfinite(number):
        raise ValueError('geometry values must be finite real numbers')
    return number


def validate_geometry(payload):
    """Check the original 26-circle constraints and recompute all public metrics."""
    if type(payload) is not dict or set(payload) != {'centers', 'radii'}:
        raise ValueError('geometry must contain only centers and radii')
    centers, radii = payload['centers'], payload['radii']
    if type(centers) is not list or len(centers) != 26 or type(radii) is not list or len(radii) != 26:
        raise ValueError('geometry requires exactly 26 centers and radii')
    points = []
    for center in centers:
        if type(center) is not list or len(center) != 2:
            raise ValueError('each center must have exactly two coordinates')
        points.append((_number(center[0]), _number(center[1])))
    sizes = [_number(radius) for radius in radii]
    for (x, y), radius in zip(points, sizes):
        if radius < 0 or x - radius < -TOLERANCE or y - radius < -TOLERANCE \
                or x + radius > 1 + TOLERANCE or y + radius > 1 + TOLERANCE:
            raise ValueError('circle is outside the square or has negative radius')
    for i, (x, y) in enumerate(points):
        for j in range(i + 1, len(points)):
            xx, yy = points[j]
            if math.hypot(x - xx, y - yy) < sizes[i] + sizes[j] - TOLERANCE:
                raise ValueError('circles overlap')
    total = math.fsum(sizes)
    return {'validity': 1.0, 'sum_radii': total, 'target_ratio': total / TARGET,
            'combined_score': total / TARGET}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('geometry JSON contains duplicate fields')
        result[key] = value
    return result


def read_geometry_payload(path):
    """Read and validate geometry once from a bounded no-follow regular file."""
    if not hasattr(os, 'O_NOFOLLOW'):
        raise RuntimeError('safe geometry reading requires no-follow file opens')
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
    try:
        fd = os.open(Path(path), flags)
    except OSError as error:
        raise ValueError('geometry artifact cannot be safely opened') from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_GEOMETRY_BYTES:
            raise ValueError('geometry artifact must be a bounded single-link regular file')
        chunks, remaining = [], MAX_GEOMETRY_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b''.join(chunks)
        if len(data) > MAX_GEOMETRY_BYTES:
            raise ValueError('geometry artifact exceeds the size limit')
    finally:
        os.close(fd)
    try:
        payload = json.loads(data.decode('utf-8'), object_pairs_hook=_unique,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('invalid geometry JSON') from error
    validate_geometry(payload)
    return payload


def read_geometry(path):
    return validate_geometry(read_geometry_payload(path))
