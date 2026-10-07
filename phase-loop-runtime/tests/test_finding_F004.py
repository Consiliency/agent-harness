"""agent-harness#1282 board round 1, codex F004 falsifier (verbatim)."""

import json
import os

from phase_loop_runtime import panel_invoker as pi


def test_grok_copied_bearer_is_redacted_from_review_text(tmp_path):
    home = tmp_path / "operator"
    auth = home / ".grok/auth.json"
    auth.parent.mkdir(parents=True)
    token = "synthetic-grok-bearer-token"
    auth.write_text(json.dumps({"https://auth.example::id": {"key": token}}))
    (auth.parent / "agent_id").write_text("synthetic-agent")
    with pi.seat_profile(harness="grok", executable="/usr/bin/true",
                         env={"HOME": str(home)}, cwd=tmp_path) as (_, profile):
        args = profile.mount_args
        copied = next(os.pread(int(args[i + 1]), 1_000_000, 0)
                      for i, arg in enumerate(args)
                      if arg == "--file" and args[i + 2].endswith("/.grok/auth.json"))
        assert token.encode() in copied
        assert token not in pi._redact_seat_credentials("REVIEW END\nAGREE\n" + token)
