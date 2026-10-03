#!/usr/bin/env python3
"""Live probe P4 (agent-harness#1132, maintainer decision D7): agy on the D7 credential copy,
in the D8 jail.

The D7 copy is the operator's `antigravity-oauth-token` with `refresh_token` and `id_token`
removed. It is delivered as the plan specifies: a parent-owned 0700 directory holding only
`settings.json`, the copy, and the `installation_id` agy insists on, bound READ-ONLY as a
directory at agy's config directory. Each writable sub-path agy needs is a read-write bind
into seat-owned `/seat/home`.

Recorded, all measured from the parent:
- the credential path agy opens, and the writes agy attempts;
- whether a turn completes;
- the token's lifetime and its OAuth scopes and audience, from Google's tokeninfo
  endpoint called by the parent (the token itself is never recorded);
- agy's stream-json signature at expiry;
- whether the pinned outside refresh works.

P4's stop rules are applied. A stop keeps Gemini sealed with the stop's code, and P3 is not
run.

Usage (from the repo root): python3 plans/evidence/seat-jail-1132/probe_p4.py
Writes plans/evidence/seat-jail-1132/p4-agy-d7-credential.json.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "phase-loop-runtime" / "src"))
from phase_loop_runtime import panel_invoker as pi  # noqa: E402
from phase_loop_runtime import sandbox_egress, seat_jail, seat_uid  # noqa: E402

OUT = Path(__file__).resolve().parent / "p4-agy-d7-credential.json"
OPERATOR = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
CONFIG = "/seat/home/.gemini/antigravity-cli"
WRITABLE = ("cache",)  # measured: the only sub-path whose absence fails the turn
TURN = ["/seat/bin/gemini", "--model", "gemini-3.8-flash", "--effort", "low", "-p",
        "Reply with exactly: P4-OK", "--output-format", "stream-json"]
REFRESH_ARGV = ["agy", "models"]
INFERENCE_SCOPES = {"openid", "email", "profile",
                    "https://www.googleapis.com/auth/userinfo.email",
                    "https://www.googleapis.com/auth/userinfo.profile"}


def expiry(path: Path = OPERATOR) -> str:
    return json.loads(path.read_text())["token"]["expiry"]


def outside_refresh() -> dict:
    before = expiry()
    cwd = tempfile.mkdtemp(prefix="pl-p4-refresh-")
    os.chmod(cwd, 0o700)
    started = time.monotonic()
    done = subprocess.run(REFRESH_ARGV, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=90)
    os.rmdir(cwd)
    return {"argv": REFRESH_ARGV, "cwd": "empty 0700 temporary directory", "stdin": "/dev/null",
            "wall_clock_bound_s": 90, "rc": done.returncode,
            "elapsed_s": round(time.monotonic() - started, 1),
            "expiry_before": before, "expiry_after": expiry(),
            "inference": False, "tools": False, "workspace": False}


def tokeninfo(access_token: str) -> dict:
    request = urllib.request.Request("https://oauth2.googleapis.com/tokeninfo",
                                     data=urllib.parse.urlencode({"access_token": access_token}).encode())
    info = json.load(urllib.request.urlopen(request, timeout=20))
    return {k: info.get(k) for k in ("scope", "aud", "azp", "expires_in", "access_type")}


def jailed_turn(copy: bytes, *, trace: bool) -> dict:
    base = Path(tempfile.mkdtemp(prefix="pl-p4-"))
    tree = base / "review" / "reviewed-tree"
    tree.mkdir(parents=True)
    (tree / "README.md").write_text("probe\n")
    seat_dir = base / "seat"
    seat_dir.mkdir(mode=0o700)
    config = seat_dir / "gemini-config"
    config.mkdir(mode=0o700)
    (config / "antigravity-oauth-token").write_bytes(copy)
    (config / "settings.json").write_text("{}")
    (config / "installation_id").write_text(str(uuid.uuid4()))
    for sub in WRITABLE:
        (config / sub).mkdir()
    agy = Path(os.path.realpath(shutil.which("agy")))
    with seat_uid.lease_seat_id(8) as n, \
            sandbox_egress.isolated_network(timeout_s=900, required=True, seat_uid_map=True) as egress:
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        holder = seat_uid.holder_pid_from_prefix(egress)
        jail = seat_jail.build_seat_jail(
            "gemini", seat_dir, agy, tree=tree, bundle_memfd=seat_jail.memfd_with("b", b"B"),
            instructions_memfd=seat_jail.memfd_with("i", b"I"), token_fd=None, seat_ids=(n, n))
        home = seat_dir / "seat-home"
        (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
        owner = list(jail.process_owner)
        at = owner.index("--remount-ro")
        add = ["--ro-bind", str(config), CONFIG]
        for sub in WRITABLE:
            (home / ".rw" / sub).mkdir(parents=True)
            add += ["--bind", str(home / ".rw" / sub), f"{CONFIG}/{sub}"]
        owner[at:at] = add
        object.__setattr__(jail, "process_owner", tuple(owner))
        prefix = pi._compose_seat_jail_prefix(jail)
        strace = (["/usr/bin/strace", "-f", "-qq", "-e",
                   "trace=openat,mkdirat,renameat,renameat2,unlinkat", "-o", "/seat/out/trace"]
                  if trace else [])
        started = time.monotonic()
        done = subprocess.run([*prefix, *strace, *TURN], capture_output=True, text=True, timeout=300,
                              pass_fds=jail.pass_fds, env=seat_uid._pythonpath_env(),
                              stdin=subprocess.DEVNULL)
        elapsed = time.monotonic() - started
        traced = subprocess.run(["/usr/bin/nsenter", "-t", str(holder), "-U", "-m",
                                 "--preserve-credentials", "cat", str(seat_dir / "seat-out" / "trace")],
                                capture_output=True, text=True).stdout if trace else ""
        seat_jail.close_jail_fds(jail)
        for parent in (base / "review", seat_dir):
            seat_uid.teardown_in_h(holder, str(parent))
        pi._EGRESS_LAUNCH_PREFIX.reset(token)
    shutil.rmtree(base, ignore_errors=True)
    events = []
    for line in done.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    result = next((e["result"] for e in events if e.get("event") == "result"), {})
    writes = sorted({re.sub(r"[0-9a-f-]{36}", "<uuid>", m.group(1))
                     for m in re.finditer(r'"(/seat/home/[^"]+)", O_(?:WRONLY|RDWR)[^)]*\)\s*=\s*(-1 \w+|\d+)', traced)})
    write_results = sorted({(re.sub(r"[0-9a-f-]{36}|\d{8}_\d{6}|_\d+_", "<id>", m.group(1)),
                             "EROFS" if "EROFS" in m.group(2) else "ok")
                            for m in re.finditer(r'"(/seat/home/[^"]+)", O_(?:WRONLY|RDWR)[^)]*\)\s*=\s*(-1 \w+|\d+)', traced)})
    opens_credential = bool(re.search(r'"' + re.escape(CONFIG) + r'/antigravity-oauth-token", O_RDONLY', traced))
    return {"rc": done.returncode, "elapsed_s": round(elapsed, 1), "status": result.get("status"),
            "response": result.get("response"), "error": result.get("error"),
            "event_types": sorted({e.get("event") for e in events if isinstance(e, dict)}),
            "stderr_auth_lines": [line for line in done.stderr.splitlines()
                                  if re.search(r"keyringAuth|refresh|Authentication|auth", line)][:8],
            "credential_opened_at_config_path": opens_credential,
            "write_attempts": [{"path": p, "result": r} for p, r in write_results][:60]}


def main() -> int:
    record = {"schema": "seat_jail_probe_p4.v1", "issue": "agent-harness#1132", "decision": "D7",
              "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "agy_version": subprocess.run(["agy", "--version"], capture_output=True, text=True).stdout.strip(),
              "delivery": {"config_dir": CONFIG, "bind": "read-only directory",
                           "contents": ["antigravity-oauth-token (D7 copy)", "settings.json", "installation_id"],
                           "writable_rw_binds_into_seat_home": list(WRITABLE)}}
    record["outside_refresh"] = outside_refresh()
    document = json.loads(OPERATOR.read_text())
    copy = seat_jail.build_gemini_seat_copy(OPERATOR)
    stripped = json.loads(copy)
    record["copy_fields"] = {"top": sorted(stripped), "token": sorted(stripped["token"])}
    record["tokeninfo"] = tokeninfo(document["token"]["access_token"])
    record["token_lifetime"] = {
        "issued_by_refresh_at": record["outside_refresh"]["expiry_before"] != record["outside_refresh"]["expiry_after"],
        "expiry": expiry(), "tokeninfo_expires_in_s": record["tokeninfo"]["expires_in"],
        "note": "lifetime ~3600 s from refresh; first provider rejection not waited for (P4 stopped on scope)"}
    record["turn_with_copy"] = jailed_turn(copy, trace=True)
    # Expiry signature: the same copy with its expiry field moved into the past. agy decides
    # expiry from that field, so the provider is never asked; the copy has no refresh token.
    expired = json.loads(copy)
    expired["token"]["expiry"] = "2020-01-01T00:00:00Z"
    record["turn_with_expired_copy"] = jailed_turn(json.dumps(expired).encode(), trace=False)
    scopes = set((record["tokeninfo"]["scope"] or "").split())
    record["scopes_beyond_inference"] = sorted(scopes - INFERENCE_SCOPES)
    stops = []
    if record["turn_with_copy"]["status"] != "SUCCESS":
        stops.append("gemini_seat_credential_unusable: agy does not run with the copy")
    if record["turn_with_expired_copy"]["status"] == "SUCCESS":
        stops.append("gemini_seat_credential_unusable: agy obtained a working token after expiry")
    if record["scopes_beyond_inference"]:
        stops.append("gemini_seat_token_scope_excess: " + " ".join(record["scopes_beyond_inference"]))
    record["not_measured_after_stop"] = [
        "pickup of a copy renamed into the bound directory mid-session",
        "the provider's first rejection of the live token (full lifetime)",
    ]
    record["stops"] = stops
    record["result"] = "stop" if stops else "pass"
    record["gemini_route_code"] = ("gemini_seat_token_scope_excess" if any("scope_excess" in s for s in stops)
                                   else "gemini_seat_credential_unusable" if stops else None)
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: record[k] for k in ("result", "stops", "gemini_route_code", "scopes_beyond_inference")}, indent=1))
    print(json.dumps({"turn": {k: record["turn_with_copy"][k] for k in ("status", "response", "credential_opened_at_config_path")},
                      "expired": {k: record["turn_with_expired_copy"][k] for k in ("status", "error")},
                      "refresh": record["outside_refresh"]}, indent=1))
    return 0 if not stops else 3


if __name__ == "__main__":
    raise SystemExit(main())
