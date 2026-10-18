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
        verify(Path(path), json.loads(MANIFEST.read_text())['generated_outputs'])
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    if reporter and (reporter.stats.get('skipped') or reporter.stats.get('xfailed')):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
