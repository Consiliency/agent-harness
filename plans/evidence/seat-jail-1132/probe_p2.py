#!/usr/bin/env python3
"""Live probe P2 (agent-harness#1132): the Claude seat token on the production fd channel.

Two jailed Claude legs run on the production D8 chain, each over a fresh staged repo whose
commit subject is random:

- ``seat_token``: the maintainer's seat token, read from its production location. The seat
  must run ``git log -1 --format=%s`` in /seat/tree and quote the subject. This shows the
  token reaches the TUI only through the drained pipe named by
  ``CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`` and authenticates it.
- ``rejected_token``: a syntactically valid DUMMY token, planted as a bound override record
  (plan amendment A4) in a throwaway 0700 directory (only the override's location moves; the
  jail's pass store stays put). It records the TUI's signature for a token the provider rejects. Only fixed
  signature literals are recorded, never the PTY tail itself.

The token's VALUE never appears in this record: it is recorded only as "present". Not
measured here (they need the maintainer): the token's scope and expiry, whether usage
bills to the subscription, and the revocation check with a sacrificial token.

Usage (from the repo root, inside a session keyring):
  PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.seat_keyring_exec -- \\
      python3 plans/evidence/seat-jail-1132/probe_p2.py
Writes plans/evidence/seat-jail-1132/p2-claude-seat-token.json.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "phase-loop-runtime" / "src"))

from phase_loop_runtime import panel_invoker as pi  # noqa: E402
from phase_loop_runtime import review_stage, sandbox_egress, seat_jail, seat_uid  # noqa: E402

OUT = Path(__file__).resolve().parent / "p2-claude-seat-token.json"
DUMMY_TOKEN = b"sk-ant-oat01-" + b"x" * 95

# Fixed literals a rejected-token tail may carry; the record keeps only which ones matched.
SIGNATURES = (
    "401", "403", "Invalid API key", "invalid_api_key", "authentication_error",
    "OAuth token has expired", "OAuth token revoked", "Invalid bearer token",
    "Please run /login", "/login", "API Error", "Unauthorized", "token",
)


def _staged_review(base: Path, subject: str):
    repo = base / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@e.st"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm",
                    subject], check=True)
    review = base / "review"
    review.mkdir()
    staged = review_stage.stage_review_tree(repo, review)
    staged.rename(review / seat_jail.HOST_TREE_DIRNAME)
    auth = types.SimpleNamespace(staged_tree_sha256=review_stage.review_tree_manifest_sha256(
        review / seat_jail.HOST_TREE_DIRNAME))
    return review, auth


def _jailed_leg(base: Path) -> dict[str, object]:
    subject = "seat-jail-p2-" + hashlib.sha256(os.urandom(8)).hexdigest()[:12]
    review, auth = _staged_review(base, subject)
    instructions = ("Run `git log -1 --format=%s` in /seat/tree and reply with its exact output "
                    "on one line, then the verdict AGREE.")
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    sink: list = []
    with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
            sandbox_egress.isolated_network(timeout_s=1200, required=True, seat_uid_map=True) as egress:
        reset = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        try:
            seat = pi._prepare_jailed_claude(review, base / "seat", auth, n,
                                             seat_uid.holder_pid_from_prefix(egress),
                                             ("BUNDLE: see the tree.", instructions))
            prompt = pi._render_broker_pointer_prompt(
                "BUNDLE: see the tree.", instructions,
                source_commit=(review / seat_jail.HOST_TREE_DIRNAME / ".git"
                               / "phase-loop-source-commit").read_text().strip(),
                staged_tree_sha256=auth.staged_tree_sha256)
            status, text = pi._exec_jailed_claude_leg(
                seat, timeout_s=600, backstop_s=900, model=None, effort="low", prompt=prompt,
                broker_evidence={}, failure_detail_sink=sink)
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(reset)
    failure = sink[-1] if sink else None
    tail = failure.raw if failure is not None else ""
    return {
        "status": status,
        "subject_quoted": subject in text,
        "detail": failure.template if failure is not None else None,
        "notices": list(seat.notices),
        "signatures_in_tail": [s for s in SIGNATURES if re.search(re.escape(s), tail)],
    }


def main() -> int:
    digest = seat_jail.jail_profile_digest("claude")
    passed, reason = seat_jail.pass_record_verdict(digest)
    if not passed:
        raise SystemExit(f"no recorded jail pass for {digest[:16]}: {reason}")
    from phase_loop_runtime import seat_credentials as _credentials

    if not _credentials.override_decision().applies:
        raise SystemExit("no stored seat-token override applies to this session "
                         "(store one with `phase-loop seat-sandbox store-token`)")
    retention = seat_uid.retention_dir()
    retained_before = sorted(os.listdir(retention)) if retention.exists() else []
    with tempfile.TemporaryDirectory(prefix="pl-p2-") as scratch:
        scratch = Path(scratch)
        (scratch / "seat").mkdir()
        seat_token = _jailed_leg(scratch / "seat")
        # The rejected-token leg reads a DUMMY token from a throwaway 0700 directory. Only the
        # override's location moves: the jail's pass store must stay where the launch gate
        # reads it. Since plan amendment A4 an override is used only as a bound record (the
        # token with the session's account), so the dummy is planted as one; a raw token file
        # would be ignored and the leg would run on the login instead.
        from phase_loop_runtime import seat_credentials

        dummy = scratch / "dummy-credentials" / "claude.override.json"
        dummy.parent.mkdir(mode=0o700)
        os.chmod(dummy.parent, 0o700)
        identity = seat_credentials.ClaudeCredentialAdapter().current_identity()
        if identity is None:
            raise SystemExit("no Claude login: the rejected-token leg needs the session's "
                             "account and organization")
        fd = os.open(dummy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema": seat_credentials.RECORD_SCHEMA, "account": identity.account,
                       "organization": identity.organization,
                       "token": DUMMY_TOKEN.decode("ascii")}, handle)
        adapter = seat_credentials.ClaudeCredentialAdapter
        real_paths = adapter.record_path, adapter.legacy_path
        adapter.record_path = lambda self: dummy
        adapter.legacy_path = lambda self: dummy.with_name("claude")
        try:
            (scratch / "rejected").mkdir()
            rejected = _jailed_leg(scratch / "rejected")
        finally:
            adapter.record_path, adapter.legacy_path = real_paths
        # P2 ends by confirming the seat token still authenticates.
        (scratch / "after").mkdir()
        after = _jailed_leg(scratch / "after")
    retained_after = sorted(os.listdir(retention)) if retention.exists() else []
    record = {
        "schema": "seat_jail_p2_claude_seat_token.v1",
        "issue": "agent-harness#1132",
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "profile_digest": digest,
        "jail_pass": reason,
        "seat_token": "present",
        "channel": "drained pipe named by CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "legs": {"seat_token": seat_token, "rejected_token": rejected,
                 "seat_token_after": after},
        "new_retention_records": sorted(set(retained_after) - set(retained_before)),
        "not_measured": ["token scope and expiry", "billing to the subscription",
                         "revocation stops a later launch (needs a sacrificial token)"],
    }
    ok = (seat_token["status"] == "OK" and seat_token["subject_quoted"]
          and after["status"] == "OK" and after["subject_quoted"]
          and rejected["status"] != "OK"
          and not str(rejected["detail"] or "").startswith("seat_sandbox_")
          and not record["new_retention_records"]
          and not any("token_in_output" in str(leg["detail"])
                      for leg in (seat_token, rejected, after)))
    record["result"] = "pass" if ok else "stop"
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"P2 {record['result']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
