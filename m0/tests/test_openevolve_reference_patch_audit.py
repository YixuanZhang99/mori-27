"""Recorded upstream patches are checked against the selected parent source."""
import hashlib

import pytest

from zoo.circle_packing.reference_patch_audit import audit_reference_patches


def test_worker_error_is_only_classified_after_replaying_original_diff(tmp_path):
    parent = '# EVOLVE-BLOCK-START\nx = 1\n# EVOLVE-BLOCK-END\n'
    digest = hashlib.sha256(parent.encode()).hexdigest()
    directory = tmp_path / 'parent-programs'
    directory.mkdir()
    (directory / (digest + '.py')).write_text(parent)
    trace = {'iterations': [{'iteration': 1, 'state': 'worker_error', 'sampled_parent_id': 'p',
                             'sampled_parent_sha256': digest, 'error_sha256': hashlib.sha256(
                                 b'None of the 1 SEARCH block(s) matched the parent program').hexdigest()}]}
    provider = {'iterations': [{'iteration': 1, 'state': 'matched', 'call_id': 'a' * 64}]}
    response = '<<<<<<< SEARCH\nx = 2\n=======\nx = 3\n>>>>>>> REPLACE\n'
    bundle = {'calls': [{'prepared': {'call_id': 'a' * 64}, 'outcome': {'outcome': 'returned', 'result': response}}]}
    report = audit_reference_patches(trace, provider, bundle, parent_directory=directory)
    assert report['iterations'][0]['patch_state'] == 'no_matching_blocks'
    assert report['iterations'][0]['worker_error_explained'] is True
    (directory / (digest + '.py')).write_text('tampered')
    with pytest.raises(ValueError, match='parent'):
        audit_reference_patches(trace, provider, bundle, parent_directory=directory)


def test_candidate_must_match_independently_applied_patch(tmp_path):
    parent = '# EVOLVE-BLOCK-START\nx = 1\n# EVOLVE-BLOCK-END\n'
    child = '# EVOLVE-BLOCK-START\nx = 2\n# EVOLVE-BLOCK-END\n'
    digest = hashlib.sha256(parent.encode()).hexdigest()
    (tmp_path / (digest + '.py')).write_text(parent)
    trace = {'iterations': [{'iteration': 1, 'state': 'candidate', 'sampled_parent_id': 'p', 'parent_id': 'p',
                             'sampled_parent_sha256': digest, 'program_sha256': hashlib.sha256(child.encode()).hexdigest()}]}
    provider = {'iterations': [{'iteration': 1, 'state': 'matched', 'call_id': 'a' * 64}]}
    response = '<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n'
    bundle = {'calls': [{'prepared': {'call_id': 'a' * 64}, 'outcome': {'outcome': 'returned', 'result': response}}]}
    assert audit_reference_patches(trace, provider, bundle, parent_directory=tmp_path)['iterations'][0]['patch_state'] == 'candidate'
    trace['iterations'][0]['program_sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='candidate'):
        audit_reference_patches(trace, provider, bundle, parent_directory=tmp_path)
