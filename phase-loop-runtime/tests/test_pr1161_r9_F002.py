import errno
import os
from pathlib import Path

import pytest

from phase_loop_runtime import sandbox_retention


def test_stage_creation_failure_is_typed(tmp_path, monkeypatch):
    scratch = tmp_path / "pl-review-stage-live"
    scratch.mkdir()
    real_open = os.open

    def refuse_stage(path, flags, mode=0o777, **kwargs):
        if (Path(path).name.startswith(scratch.name + ".owner.")
                and flags & os.O_CREAT):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", refuse_stage)
    with pytest.raises(sandbox_retention.ScratchRecordError, match="could not publish"):
        sandbox_retention.claim_scratch_dir(scratch)

    assert not list(tmp_path.glob("*.tmp"))
    assert not sandbox_retention.scratch_owner_gone(scratch)
