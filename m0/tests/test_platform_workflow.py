"""Protect acceptance against green runs caused by skips or stale inventories."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

PLUGIN = Path(__file__).with_name("conftest.py")
LAUNCH = """
import importlib.util
import sys
import pytest

spec = importlib.util.spec_from_file_location("isolated_platform_plugin", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if sys.argv[2] == "stale_inventory":
    module.LINUX_FUNCTIONS["test_eval_governance.py"] = {"test_removed_from_source"}
raise SystemExit(pytest.main(sys.argv[3:], plugins=[module]))
"""


def run_isolated_pytest(tmp_path: Path, source: str, *, stale: bool = False):
    # A second module ensures collection skips would otherwise still exit zero.
    (tmp_path / "test_control.py").write_text("def test_control():\n    assert True\n")
    (tmp_path / "test_subject.py").write_text(source)
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    return subprocess.run(
        [sys.executable, "-c", LAUNCH, str(PLUGIN),
         "stale_inventory" if stale else "normal", str(tmp_path),
         "-c", str(config), "-q", "-p", "no:cacheprovider", "--fail-on-skip"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("source,expected_code,expected_summary", [
    ("def test_subject():\n    assert True\n", 0, "2 passed"),
    ("import pytest\ndef test_subject():\n    pytest.skip('dependency unavailable')\n",
     1, "1 skipped"),
    ("import pytest\n@pytest.mark.xfail(reason='known defect')\ndef test_subject():\n    assert False\n",
     1, "1 xfailed"),
    ("import pytest\npytest.skip('module dependency unavailable', allow_module_level=True)\n",
     1, "1 skipped"),
], ids=["passing", "runtime-skip", "xfail", "collection-skip"])
def test_acceptance_skip_policy(tmp_path, source, expected_code, expected_summary):
    result = run_isolated_pytest(tmp_path, source)
    output = result.stdout + result.stderr
    assert result.returncode == expected_code, output
    assert expected_summary in output
    if expected_code:
        assert "acceptance rejected:" in output
    else:
        assert "acceptance rejected:" not in output


def test_stale_platform_inventory_refuses_collection(tmp_path):
    result = run_isolated_pytest(tmp_path, "def test_subject():\n    assert True\n", stale=True)
    output = result.stdout + result.stderr
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "Linux test inventory names missing tests" in output
    assert "test_removed_from_source" in output
