"""JEVHOST S3 on native Windows, unpatched: review is refused before any spawn.

`test_jevdrill_launch_merge.py` proves the refusal everywhere by patching the
``_native_windows()`` seam. This file runs the same refusal with the seam unpatched, so
it only means anything on native Windows, where the companion workflow's dispatched
legs run it. It imports nothing beyond ``launcher``, which imports on native Windows.
"""

import os
import subprocess

import pytest

from phase_loop_runtime import launcher, windows_process

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows review refusal proof")


def test_native_windows_review_is_refused_unpatched(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a process was started for a refused review launch")

    assert launcher._native_windows() is True
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(windows_process, "run_owned", forbidden)
    monkeypatch.setattr(launcher, "_launch_windows_owned", forbidden)
    with pytest.raises(ValueError, match="review_unsupported_on_windows"):
        launcher.launch(["codex", "exec", "-"], action="review", ephemeral_monitor=True)
