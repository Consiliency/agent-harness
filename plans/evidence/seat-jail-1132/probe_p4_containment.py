#!/usr/bin/env python3
"""P4 containment probe (agent-harness#1132, maintainer ruling "prove then enable",
2026-09-29).

Gemini gets its tools only if both of these are proven live:

(a) The D7 copy that enters the jail holds ONLY a short-lived access token: no refresh
    token and no client secret. This is proven by inspecting the staged copy's structure,
    never by logging token bytes. The token's remaining lifetime at staging is recorded.
    - agy must run on that copy, or the probe stops with `gemini_seat_credential_unusable`.
    - agy must not refresh the token in place, or the probe stops with
      `gemini_seat_token_refreshed_in_jail`.

(b) From inside the jail, network egress reaches ONLY the hosts agy needs for inference,
    as measured from agy's real traffic. Other Google Cloud API hosts must give no real
    reply. If they do, and the egress namespace cannot enforce host-level limits, the probe
    stops with `gemini_seat_egress_unconfined`.

Usage (from the repo root): python3 plans/evidence/seat-jail-1132/probe_p4_containment.py
Writes plans/evidence/seat-jail-1132/p4-containment.json.
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
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "phase-loop-runtime" / "src"))
from phase_loop_runtime import panel_invoker as pi  # noqa: E402
from phase_loop_runtime import sandbox_egress, seat_jail, seat_uid  # noqa: E402

OUT = Path(__file__).resolve().parent / "p4-containment.json"
OPERATOR = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
CONFIG = "/seat/home/.gemini/antigravity-cli"
FORBIDDEN = ("storage.googleapis.com", "cloudresourcemanager.googleapis.com",
             "compute.googleapis.com", "iam.googleapis.com")
TURN = ["/seat/bin/gemini", "--model", "gemini-3.8-flash", "--effort", "low", "-p",
        "Reply with exactly: P4-OK", "--output-format", "stream-json"]
SECRET_KEYS = {"refresh_token", "client_secret", "id_token"}


def keys_of(value, prefix=""):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield f"{prefix}{key}"
            yield from keys_of(inner, f"{prefix}{key}.")


def staged_structure(copy: bytes) -> dict:
    document = json.loads(copy)
    keys = sorted(keys_of(document))
    expiry = datetime.datetime.fromisoformat(document["token"]["expiry"][:26].rstrip("Z") + "+00:00")
    remaining = (expiry - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    return {"keys": keys,
            "secret_keys_present": sorted({k.split(".")[-1] for k in keys} & SECRET_KEYS),
            "token_value_is_nonempty_string": isinstance(document["token"].get("access_token"), str)
            and bool(document["token"]["access_token"]),
            "remaining_lifetime_at_staging_s": int(remaining)}


class Seat:
    """One gemini seat on the real D8 chain with the D7 copy delivered as P4 pinned."""

    def __init__(self, copy: bytes):
        self.base = Path(tempfile.mkdtemp(prefix="pl-p4c-"))
        self.tree = self.base / "review" / "reviewed-tree"
        self.tree.mkdir(parents=True)
        self.seat_dir = self.base / "seat"
        self.seat_dir.mkdir(mode=0o700)
        self.config = self.seat_dir / "gemini-config"
        self.config.mkdir(mode=0o700)
        (self.config / "antigravity-oauth-token").write_bytes(copy)
        (self.config / "settings.json").write_text("{}")
        (self.config / "installation_id").write_text(str(uuid.uuid4()))
        for sub in ("cache", "log"):
            (self.config / sub).mkdir()

    def __enter__(self):
        self.lease = seat_uid.lease_seat_id(8)
        n = self.lease.__enter__()
        self.net = sandbox_egress.isolated_network(timeout_s=900, required=True, seat_uid_map=True)
        egress = self.net.__enter__()
        self.token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        self.holder = seat_uid.holder_pid_from_prefix(egress)
        agy = Path(os.path.realpath(shutil.which("agy")))
        self.jail = seat_jail.build_seat_jail(
            "gemini", self.seat_dir, agy, tree=self.tree, bundle_memfd=seat_jail.memfd_with("b", b"B"),
            instructions_memfd=seat_jail.memfd_with("i", b"I"), token_fd=None, seat_ids=(n, n))
        home = self.seat_dir / "seat-home"
        (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
        add = ["--ro-bind", str(self.config), CONFIG]
        for sub in ("cache", "log"):
            (home / ".rw" / sub).mkdir(parents=True)
            add += ["--bind", str(home / ".rw" / sub), f"{CONFIG}/{sub}"]
        owner = list(self.jail.process_owner)
        at = owner.index("--remount-ro")
        owner[at:at] = add
        object.__setattr__(self.jail, "process_owner", tuple(owner))
        self.prefix = pi._compose_seat_jail_prefix(self.jail)
        return self

    def run(self, argv, timeout=300):
        # bwrap READS the seccomp and data memfds; rewind them so every run of this seat
        # gets the same bytes (an exhausted fd makes bwrap fail before the seat runs).
        for fd in self.jail.pass_fds:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
            except OSError:
                pass
        return subprocess.run([*self.prefix, *argv], capture_output=True, text=True, timeout=timeout,
                              pass_fds=self.jail.pass_fds, env=seat_uid._pythonpath_env(),
                              stdin=subprocess.DEVNULL)

    def in_h(self, script):
        return subprocess.run(["/usr/bin/nsenter", "-t", str(self.holder), "-U", "-m",
                               "--preserve-credentials", "/bin/sh", "-c", script],
                              capture_output=True, text=True).stdout

    def __exit__(self, *exc):
        seat_jail.close_jail_fds(self.jail)
        for parent in (self.base / "review", self.seat_dir):
            seat_uid.teardown_in_h(self.holder, str(parent))
        pi._EGRESS_LAUNCH_PREFIX.reset(self.token)
        self.net.__exit__(*exc)
        self.lease.__exit__(*exc)
        shutil.rmtree(self.base, ignore_errors=True)


def http_probe(seat: Seat, host: str) -> dict:
    done = seat.run(["/usr/bin/curl", "-sS", "-o", "/dev/null", "--max-time", "15",
                     "-w", "%{http_code} %{remote_ip}", f"https://{host}/"], timeout=60)
    code, _, ip = done.stdout.strip().partition(" ")
    if "bwrap:" in done.stderr or "setpriv:" in done.stderr or "nsenter:" in done.stderr:
        # The probe itself failed to reach the seat: never read that as "no reply".
        raise SystemExit(f"probe harness failure for {host}: {done.stderr.strip()[-300:]}")
    return {"http_code": code, "remote_ip": ip, "real_reply": code not in ("", "000"),
            "curl_error": done.stderr.strip()[-200:]}


def resolve(seat: Seat, host: str) -> list[str]:
    done = seat.run(["/usr/bin/getent", "ahostsv4", host], timeout=60)
    return sorted({line.split()[0] for line in done.stdout.splitlines() if line.strip()})


def main() -> int:
    record = {"schema": "seat_jail_probe_p4_containment.v1", "issue": "agent-harness#1132",
              "ruling": "maintainer 'prove then enable', 2026-09-29",
              "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    copy = seat_jail.build_gemini_seat_copy(OPERATOR)
    structure = staged_structure(copy)
    record["a_staged_copy"] = structure
    with Seat(copy) as seat:
        turn = seat.run(["/usr/bin/strace", "-f", "-qq", "-e", "trace=connect", "-o", "/seat/out/trace", *TURN])
        events = [json.loads(line) for line in turn.stdout.splitlines() if line.startswith("{")]
        result = next((e["result"] for e in events if e.get("event") == "result"), {})
        trace = seat.in_h(f"cat {seat.seat_dir}/seat-out/trace")
        logs = seat.in_h(f"cat {seat.seat_dir}/seat-home/.rw/log/* 2>/dev/null")
        used_ips = sorted({m for m in re.findall(r'inet_addr\("([^"]+)"\)', trace)
                           if not m.startswith(("127.", "10.0.2."))})
        hosts = sorted(set(re.findall(r"https?://([a-z0-9.-]+\.googleapis\.com)", logs + turn.stderr)))
        # Did agy put a token anywhere the seat can write? (a count only, never bytes)
        token_files = seat.in_h(
            f"grep -rlE 'access_token|refresh_token' {seat.seat_dir}/seat-home {seat.seat_dir}/seat-out "
            f"2>/dev/null | wc -l").strip()
        copy_after = (seat.config / "antigravity-oauth-token").read_bytes()
        record["a_turn"] = {"status": result.get("status"), "response": result.get("response"),
                            "staged_copy_unchanged": copy_after == copy,
                            "files_in_seat_writable_dirs_mentioning_a_token": int(token_files or 0)}
        record["b_inference_hosts_from_agy_logs"] = hosts
        record["b_ips_agy_connected_to"] = used_ips
        record["b_inference_host_probe"] = {h: http_probe(seat, h) for h in hosts}
        record["b_forbidden_host_probe"] = {h: http_probe(seat, h) for h in FORBIDDEN}
        resolved = {h: resolve(seat, h) for h in (*hosts, *FORBIDDEN)}
        record["b_resolved_inside_jail"] = resolved
        inference_ips = set().union(*(resolved[h] for h in hosts)) if hosts else set()
        record["b_forbidden_ips_shared_with_inference_hosts"] = {
            h: sorted(set(resolved[h]) & inference_ips) for h in FORBIDDEN}
    expired = json.loads(copy)
    expired["token"]["expiry"] = "2020-01-01T00:00:00Z"
    with Seat(json.dumps(expired).encode()) as seat:
        again = seat.run(TURN)
        events = [json.loads(line) for line in again.stdout.splitlines() if line.startswith("{")]
        record["a_expired_copy_turn"] = next((e["result"].get("status") for e in events
                                              if e.get("event") == "result"), None)
    record["b_egress_enforcement"] = {
        "mechanism": "iptables in the per-leg network namespace (sandbox_egress.egress_rules)",
        "rules": sandbox_egress.egress_rules(),
        "host_level": False,
        "note": "rules match destination CIDRs only; there is no SNI, HTTP or DNS host filter, and "
                "Google API hosts share front-end addresses, so an address rule cannot tell them apart",
    }
    stops = []
    if not all(r["real_reply"] for r in record["b_inference_host_probe"].values()) or not hosts:
        # Control: the probe must get a real reply from agy's own inference host, or a
        # silent forbidden host proves nothing.
        raise SystemExit("control failed: no real reply from agy's inference host")
    if structure["secret_keys_present"] or not structure["token_value_is_nonempty_string"]:
        stops.append("gemini_seat_credential_unusable: staged copy is not access-token-only")
    if record["a_turn"]["status"] != "SUCCESS":
        stops.append("gemini_seat_credential_unusable: agy does not run on the access-token-only copy")
    if record["a_expired_copy_turn"] == "SUCCESS" or not record["a_turn"]["staged_copy_unchanged"] \
            or record["a_turn"]["files_in_seat_writable_dirs_mentioning_a_token"]:
        stops.append("gemini_seat_token_refreshed_in_jail")
    reachable = [h for h, r in record["b_forbidden_host_probe"].items() if r["real_reply"]]
    if reachable and not record["b_egress_enforcement"]["host_level"]:
        stops.append("gemini_seat_egress_unconfined: real replies from " + ", ".join(reachable))
    record["a_holds"] = not any("credential_unusable" in s or "refreshed" in s for s in stops)
    record["b_holds"] = not any("egress_unconfined" in s for s in stops)
    record["stops"] = stops
    record["result"] = "stop" if stops else "pass"
    record["gemini_route_code"] = (stops[0].split(":")[0] if stops else None)
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: record[k] for k in ("result", "stops", "a_holds", "b_holds", "gemini_route_code")}, indent=1))
    print(json.dumps({"forbidden": record["b_forbidden_host_probe"], "hosts": hosts,
                      "shared": record["b_forbidden_ips_shared_with_inference_hosts"],
                      "a": record["a_staged_copy"], "turn": record["a_turn"],
                      "expired": record["a_expired_copy_turn"]}, indent=1))
    return 0 if not stops else 3


if __name__ == "__main__":
    raise SystemExit(main())
