#!/usr/bin/env python3
"""Live probe for plan amendment A1 (agent-harness#1132): the jailed Claude seat on the
user's Claude LOGIN, with no seat-token override.

If an override file exists, it is moved aside by a rename within its own 0700 directory for
the run, and renamed back in a ``finally`` (the restore is verified). Recorded:
- the pre-launch seat mode for a Claude seat (expected ``jailed`` with ``credential: login``);
- one jailed leg over a fresh staged repo with a random commit subject: its credential
  source, its status, whether it quoted the subject, its notices;
- ``test_live_jailed_claude_runs_a_tool_and_quotes_it`` on the same route.

No token value is printed or recorded; the login token is recorded only as "present".

Usage (from the repo root, inside a session keyring):
  PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.seat_keyring_exec -- \\
      python3 plans/evidence/seat-jail-1132/probe_a1_login.py
Writes plans/evidence/seat-jail-1132/a1-login-route.json.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "phase-loop-runtime" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase_loop_runtime import panel_invoker as pi  # noqa: E402
from phase_loop_runtime import seat_credentials, seat_jail, seat_uid  # noqa: E402

import probe_p2  # noqa: E402  (the jailed-leg driver)

OUT = Path(__file__).resolve().parent / "a1-login-route.json"
ASIDE_SUFFIX = ".moved-aside-a1"


def _login_leg(base: Path) -> dict[str, object]:
    seen: dict[str, object] = {}
    real = pi._prepare_jailed_claude

    def spy(*args, **kwargs):
        seat = real(*args, **kwargs)
        seen["source"] = seat.source
        seen["remaining_at_launch_s"] = (int(seat.expires_at - __import__("time").time())
                                         if seat.expires_at is not None else None)
        return seat

    pi._prepare_jailed_claude = spy
    try:
        leg = probe_p2._jailed_leg(base)
    finally:
        pi._prepare_jailed_claude = real
    return {**leg, **seen}


def main() -> int:
    digest = seat_jail.jail_profile_digest("claude")
    passed, reason = seat_jail.pass_record_verdict(digest)
    if not passed:
        raise SystemExit(f"no recorded jail pass for {digest[:16]}: {reason}")
    # Since plan amendment A4 the override is the bound record (a raw token file is ignored).
    override = seat_credentials.ClaudeCredentialAdapter().record_path()
    aside = override.with_name(override.name + ASIDE_SUFFIX)
    moved = False
    if os.path.lexists(override):
        os.rename(override, aside)
        moved = True
    try:
        login = seat_credentials.read_login_token()
        if login is None:
            raise SystemExit("no Claude login found")
        board = types.SimpleNamespace(seats=[types.SimpleNamespace(
            harness="claude", seat_key="claude:a", model="m")])
        mode = pi._seat_launch_modes(
            board, mode="review",
            review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
            base_env={})[0]
        with tempfile.TemporaryDirectory(prefix="pl-a1-") as scratch:
            (Path(scratch) / "leg").mkdir()
            leg = _login_leg(Path(scratch) / "leg")
        live = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "tests/test_seat_jail_live_d8.py::test_live_jailed_claude_runs_a_tool_and_quotes_it"],
            cwd=ROOT / "phase-loop-runtime", capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": "src:tests"}, timeout=1800)
        live_summary = ([line for line in live.stdout.splitlines() if line.strip()][-1:]
                        or [""])[0]
    finally:
        if moved:
            os.rename(aside, override)
    restored = (not moved) or (os.path.isfile(override) and not os.path.lexists(aside))
    record = {
        "schema": "seat_jail_a1_login_route.v1",
        "issue": "agent-harness#1132",
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "profile_digest": digest,
        "jail_pass": reason,
        "login_token": "present",
        "override_moved_aside_and_restored": moved and restored,
        "seat_mode": mode.as_json(),
        "leg": leg,
        "live_tool_use_test": {"returncode": live.returncode, "summary": live_summary},
        "new_retention_records": [],
    }
    retention = seat_uid.retention_dir()
    if retention.exists():
        record["new_retention_records"] = sorted(os.listdir(retention))
    ok = (restored and mode.mode == "jailed" and mode.credential == "login"
          and leg.get("source") == "login" and leg["status"] == "OK" and leg["subject_quoted"]
          and live.returncode == 0 and not record["new_retention_records"])
    record["result"] = "pass" if ok else "stop"
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"A1 login route {record['result']}; override restored: {restored}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
