"""agent-harness#1282 board round 1, codex F002 falsifier (verbatim)."""

import json
import os

import pytest

from phase_loop_runtime import panel_invoker as pi


@pytest.mark.parametrize("role", [pi.SeatLaunchRole.PROVIDER_REVIEW,
                                 pi.SeatLaunchRole.PROVIDER_ADMIN])
def test_opencode_profile_does_not_copy_refresh_credentials(tmp_path, role):
    home = tmp_path / "operator"
    auth = home / ".local/share/opencode/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({"openai": {
        "type": "oauth", "access": "synthetic-access-token",
        "refresh": "synthetic-refresh-token", "expires": 9999999999999,
    }}))
    with pi.seat_profile(harness="opencode", executable="/usr/bin/true",
                         env={"HOME": str(home)}, cwd=tmp_path,
                         role=role) as (_, profile):
        args = profile.mount_args
        copied = next(os.pread(int(args[i + 1]), 1_000_000, 0)
                      for i, arg in enumerate(args)
                      if arg == "--file" and args[i + 2].endswith("/opencode/auth.json"))
        assert b"synthetic-refresh-token" not in copied
