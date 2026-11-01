"""Opt-in pytest policy for the bounded SDK qualification command."""
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qualify_openshell_sdk import MANIFEST, verify


def pytest_sessionstart(session):
    path = os.environ.get('OPENSHELL_GENERATED_DIR')
    if not path:
        raise pytest.UsageError('qualification requires OPENSHELL_GENERATED_DIR')
    try:
        verify(Path(path), json.loads(MANIFEST.read_text())['generated_outputs'], exact=True)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    if reporter and (reporter.stats.get('skipped') or reporter.stats.get('xfailed') or reporter.stats.get('xpassed')):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    result_path = os.environ.get('OPENSHELL_TEST_RESULTS')
    if result_path and reporter:
        results = {name: len(reporter.stats.get(name, [])) for name in
                   ('passed', 'failed', 'skipped', 'xfailed', 'xpassed')}
        results.update(errors=len(reporter.stats.get('error', [])),
                       collected=session.testscollected, exitstatus=int(session.exitstatus))
        Path(result_path).write_text(json.dumps(results) + '\n')
