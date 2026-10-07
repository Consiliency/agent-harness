"""The executor-review route redacts the seat's copied secrets from everything it returns
(agent-harness#1282 r2): the captured output, every streamed line and the run log.

A fake opencode prints the auth file it finds in its private home; the launch must not
hand back any access, key or refresh value."""

from __future__ import annotations

import json
import os
import shutil

import pytest

from phase_loop_runtime import launcher, sandbox_egress
from phase_loop_runtime import panel_invoker as pi

ACCESS, KEY, REFRESH = ("synthetic-opencode-access-value", "synthetic-opencode-api-key",
                        "synthetic-opencode-refresh-value")


@pytest.mark.skipif(not os.path.exists("/usr/bin/bwrap") or os.getuid() == 0
                    or shutil.which("slirp4netns") is None,
                    reason="needs the seat owner and filtered egress")
@pytest.mark.parametrize("stream", [False, True])
def test_executor_review_output_is_redacted(tmp_path, monkeypatch, capsys, stream):
    if not sandbox_egress.egress_isolation_available():
        pytest.skip("filtered review egress unavailable")
    home = tmp_path / "operator"
    auth = home / ".local/share/opencode/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({
        "anthropic": {"type": "oauth", "access": ACCESS, "refresh": REFRESH, "expires": 1},
        "openai": {"type": "api", "key": KEY}}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "opencode"
    fake.write_text("#!/bin/sh\ncat \"$HOME/.local/share/opencode/auth.json\"; echo\necho REVIEW END\n")
    fake.chmod(0o755)
    path = f"{bin_dir}{os.pathsep}/usr/bin:/bin"
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", path)
    pi._recorded_provider_hashes.cache_clear()
    work = tmp_path / "work"
    work.mkdir()
    log = tmp_path / "run" / "output.log"
    result = launcher.launch(
        ["opencode", "run", "review"], action="review", cwd=work, log_path=log,
        stream_output=stream, env={"HOME": str(home), "PATH": path},
    )
    streamed = capsys.readouterr().out
    assert "REVIEW END" in result.output, result.output  # the seat ran and printed its file
    for surface, text in (("output", result.output), ("streamed", streamed),
                          ("log", log.read_text(encoding="utf-8"))):
        for secret in (ACCESS, KEY, REFRESH):
            assert secret not in text, (surface, secret)
    assert "[credential redacted]" in result.output
