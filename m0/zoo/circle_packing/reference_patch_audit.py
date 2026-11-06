"""Recalculate pinned OpenEvolve patches from recorded parent and response.

The caller must first authenticate the reference worker, provider receipts and
frozen source. This reports patch outcomes only; it does not execute a program
or certify the complete run.
"""
import hashlib
import os
from pathlib import Path
import re
import stat


def _read_parent(directory, digest):
    if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise ValueError('reference parent digest is invalid')
    directory_fd = file_fd = None
    try:
        directory_fd = os.open(Path(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        file_fd = os.open(digest + '.py', os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid() or \
                before.st_size > 1024 * 1024:
            raise ValueError('reference parent source is not a bounded private file')
        chunks, remaining = [], 1024 * 1024 + 1
        while remaining:
            data = os.read(file_fd, remaining)
            if not data:
                break
            chunks.append(data)
            remaining -= len(data)
        data, after = b''.join(chunks), os.fstat(file_fd)
        if len(data) > 1024 * 1024 or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('reference parent source differs from its pinned digest')
        return data.decode('utf-8')
    except (OSError, UnicodeError) as error:
        raise ValueError('reference parent source cannot be safely read') from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def audit_reference_patches(trace, provider, bundle, *, parent_directory):
    """Independently apply each matched response to its recorded sampled parent."""
    from core.openevolve_interop import ProgramDatabase as _ProgramDatabase  # noqa: F401
    from core.composition.openevolve_prompt import _CONFIG, _verify_sources
    from openevolve.config import Config, PromptConfig
    from openevolve.utils.code_utils import apply_diff_blocks, enforce_evolve_blocks, extract_diffs
    import yaml
    if any(type(value) is not dict for value in (trace, provider, bundle)) or \
            type(trace.get('iterations')) is not list or type(provider.get('iterations')) is not list or \
            type(bundle.get('calls')) is not list:
        raise ValueError('reference patch audit requires recorded inputs')
    try:
        config = Config()
        _verify_sources()
        if PromptConfig(**yaml.safe_load(_CONFIG.read_text())['prompt']).programs_as_changes_description:
            raise ValueError('reference patch audit does not support description-edit mode')
        results = []
        for iteration in trace['iterations']:
            if iteration['state'] == 'not_submitted':
                continue
            number = iteration['iteration']
            output = {'iteration': number, 'patch_state': 'unverified', 'worker_error_explained': False}
            links = [row for row in provider['iterations'] if row['iteration'] == number and row['state'] == 'matched']
            if len(links) != 1 or 'sampled_parent_sha256' not in iteration:
                results.append(output)
                continue
            matching = [call for call in bundle['calls'] if call['prepared']['call_id'] == links[0]['call_id']]
            if len(matching) != 1:
                raise ValueError('reference patch lacks its unique provider receipt')
            outcome = matching[0]['outcome']
            if outcome['outcome'] != 'returned' or type(outcome['result']) is not str:
                results.append(output)
                continue
            parent = _read_parent(parent_directory, iteration['sampled_parent_sha256'])
            if iteration['state'] == 'candidate' and iteration.get('parent_id') != iteration['sampled_parent_id']:
                raise ValueError('reference candidate differs from its sampled parent')
            response = outcome['result']
            expected_error = None
            try:
                blocks = extract_diffs(response, config.diff_pattern)
            except ValueError as error:
                blocks, expected_error, state = [], str(error), 'invalid_diff'
            if expected_error is None and not blocks:
                state, expected_error = 'no_valid_diff', 'No valid diffs found in response'
            if expected_error is None:
                patched, matched = apply_diff_blocks(parent, blocks)
                if matched == 0:
                    state = 'no_matching_blocks'
                    expected_error = f'None of the {len(blocks)} SEARCH block(s) matched the parent program'
                elif patched == parent:
                    state, expected_error = 'unchanged_diff', 'Diff did not change the parent program'
                else:
                    try:
                        enforced = enforce_evolve_blocks(parent, patched)
                    except ValueError as error:
                        state, expected_error = 'invalid_scope', str(error)
                    else:
                        if enforced != patched and enforced == parent:
                            state, expected_error = 'outside_scope', 'All edits were outside the EVOLVE-BLOCK regions'
                        elif len(enforced) > config.max_code_length:
                            state = 'too_long'
                            expected_error = f'Generated code exceeds maximum length ({len(enforced)} > {config.max_code_length})'
                        else:
                            state = 'candidate'
                            candidate_sha256 = hashlib.sha256(enforced.encode('utf-8')).hexdigest()
            output['patch_state'] = state
            if iteration['state'] == 'candidate':
                if state != 'candidate' or iteration['program_sha256'] != candidate_sha256:
                    raise ValueError('reference candidate differs from its independently applied patch')
            elif iteration['state'] == 'worker_error' and expected_error is not None:
                output['worker_error_explained'] = iteration.get('error_sha256') == hashlib.sha256(
                    expected_error.encode('utf-8')).hexdigest()
            results.append(output)
        return {'schema_version': 1, 'scope': 'caller_pinned_reference_patch_outcomes',
                'performance_claim': False, 'iterations': results}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid reference patch evidence') from error
