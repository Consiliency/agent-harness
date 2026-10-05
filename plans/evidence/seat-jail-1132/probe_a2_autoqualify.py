#!/usr/bin/env python3
"""Live probe for plan amendment A2 (agent-harness#1132): the jail is qualified on first use.

On this host:
1. The recorded EC-EXECFIND-2 pass for the current jail digest (record and evidence) is
   moved aside, by a rename within the per-host store.
2. The pre-launch seat mode is decided for one Claude seat on the production route facts.
   With no pass recorded, that runs the REAL first-use qualification.
3. The probe records:
   - the mode (expected ``jailed`` with ``qualified_now``);
   - that a pass is now recorded;
   - the qualification's wall time.
4. One jailed leg runs over a fresh staged repo and must quote a random commit subject.
5. In a ``finally``, the newly written pass is removed and the original record and evidence
   are renamed back.

Usage (from the repo root, inside a session keyring):
  PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.seat_keyring_exec -- \\
      python3 plans/evidence/seat-jail-1132/probe_a2_autoqualify.py
Writes plans/evidence/seat-jail-1132/a2-first-use-qualification.json.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "phase-loop-runtime" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase_loop_runtime import panel_invoker as pi  # noqa: E402
from phase_loop_runtime import seat_jail, seat_jail_autoqualify, seat_uid  # noqa: E402

import probe_p2  # noqa: E402  (the jailed-leg driver)

OUT = Path(__file__).resolve().parent / "a2-first-use-qualification.json"
ASIDE = ".aside-a2"


def main() -> int:
    digest = seat_jail.jail_profile_digest("claude")
    passed, reason = seat_jail.pass_record_verdict(digest)
    if not passed:
        raise SystemExit(f"expected a recorded pass to move aside, got {reason}")
    store = seat_jail.jail_pass_dir()
    originals = [store / f"{digest}.json", store / f"{digest}.evidence.json"]
    failure = seat_jail_autoqualify.failure_dir() / f"{digest}.json"
    moved: list[Path] = []
    record: dict[str, object] = {
        "schema": "seat_jail_a2_first_use_qualification.v1", "issue": "agent-harness#1132",
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "profile_digest": digest,
    }
    try:
        for path in originals + ([failure] if failure.exists() else []):
            os.rename(path, path.with_name(path.name + ASIDE))
            moved.append(path)
        record["verdict_after_move_aside"] = seat_jail.pass_record_verdict(digest)[1]
        board = types.SimpleNamespace(seats=[types.SimpleNamespace(
            harness="claude", seat_key="claude:a", model="m")])
        started = time.monotonic()
        mode = pi._seat_launch_modes(
            board, mode="review",
            review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
            base_env={})[0]
        record["qualification_wall_s"] = round(time.monotonic() - started, 1)
        record["seat_mode"] = mode.as_json()
        record["mode_line"] = mode.render()
        record["verdict_after_first_use"] = seat_jail.pass_record_verdict(digest)[1]
        with tempfile.TemporaryDirectory(prefix="pl-a2-") as scratch:
            (Path(scratch) / "leg").mkdir()
            record["leg"] = probe_p2._jailed_leg(Path(scratch) / "leg")
    finally:
        for path in moved:
            if path.exists():
                path.unlink()          # the pass written just now; the original returns
            os.rename(path.with_name(path.name + ASIDE), path)
    record["original_pass_restored"] = (all(p.exists() for p in originals)
                                        and seat_jail.pass_record_verdict(digest) == (True, "pass"))
    retention = seat_uid.retention_dir()
    record["new_retention_records"] = sorted(os.listdir(retention)) if retention.exists() else []
    leg = record.get("leg", {})
    ok = (record["verdict_after_move_aside"] == "no_record"
          and record["seat_mode"]["mode"] == "jailed" and record["seat_mode"]["qualified_now"]
          and record["verdict_after_first_use"] == "pass"
          and leg.get("status") == "OK" and leg.get("subject_quoted")
          and record["original_pass_restored"] and not record["new_retention_records"])
    record["result"] = "pass" if ok else "stop"
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"A2 first-use qualification {record['result']}; original pass restored: "
          f"{record['original_pass_restored']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
