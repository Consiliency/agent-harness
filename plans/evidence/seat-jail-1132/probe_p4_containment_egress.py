#!/usr/bin/env python3
"""P4 containment probe through the seat's egress layer (agent-harness#1170; plan
agent-harness#1244 rulings S3/S4; maintainer ruling "prove then enable", 2026-09-29).

The 2026-09-29 run (p4-containment.json) proved (a) and failed (b): the namespace filtered by
address only. This re-runs both through the production egress layer -- a namespace with no
uplink whose one loopback port is bridged to srt's TLS-terminating proxy on the host -- with
the production jail and the production seat files, and real replies:

(a) Only a short-lived access token enters the jail (the staged copy's structure, never its
    bytes), agy runs a turn on it, does not refresh it in place, writes no token where the
    seat can write, and an expired copy does not run. The proxy refuses Google's token
    endpoint, so no refresh can happen through the network either.
(b) From inside the jail only the allowlisted requests reach their hosts: agy's inference
    host answers; storage, cloudresourcemanager, compute and iam are refused; the storage and
    compute paths on www.googleapis.com are refused; a request that tunnels through the
    allowed host but names storage inside TLS (Host, or SNI and Host) is REFUSED; and a
    public address has no route without the proxy.
S4  The CA key is not visible in the jail, the CA is not in the host trust store, the proxy's
    environment holds no credential, and the evidence records egress.tls_inspection.

Usage (from the repo root): python3 plans/evidence/seat-jail-1132/probe_p4_containment_egress.py
    [--check]   run every row and exit 0 on pass, 3 on a stop, without writing the record
Writes plans/evidence/seat-jail-1132/p4-containment-egress.json. Never prints or stores a
token: the copy's structure is recorded by key name, and the proxy's session URL is redacted
from every captured line.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "phase-loop-runtime" / "src"))
from phase_loop_runtime import panel_invoker as pi  # noqa: E402
from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_jail, seat_uid  # noqa: E402

OUT = Path(__file__).resolve().parent / "p4-containment-egress.json"
OPERATOR = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
HOST_TRUST_BUNDLE = Path(os.environ.get("PROBE_HOST_TRUST_BUNDLE", "/etc/ssl/certs/ca-certificates.crt"))
INFERENCE = "daily-cloudcode-pa.googleapis.com"
FORBIDDEN = ("storage.googleapis.com", "cloudresourcemanager.googleapis.com",
             "compute.googleapis.com", "iam.googleapis.com")
FORBIDDEN_PATHS = ("https://www.googleapis.com/storage/v1/b",
                   "https://www.googleapis.com/compute/v1/projects")
TURN_PROMPT = "Reply with exactly: P4-OK"
SECRET_KEYS = {"refresh_token", "client_secret", "id_token"}


def keys_of(value, prefix=""):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield f"{prefix}{key}"
            yield from keys_of(inner, f"{prefix}{key}.")


def staged_structure(copy: bytes) -> dict:
    document = json.loads(copy)
    keys = sorted(keys_of(document))
    expiry = pi._parse_agy_expiry(document["token"]["expiry"])
    remaining = (expiry - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    return {"keys": keys,
            "secret_keys_present": sorted({k.split(".")[-1] for k in keys} & SECRET_KEYS),
            "token_value_is_nonempty_string": isinstance(document["token"].get("access_token"), str)
            and bool(document["token"]["access_token"]),
            "remaining_lifetime_at_staging_s": int(remaining)}


class Seat:
    """One Gemini seat on the production chain: the proxy-only namespace, the production
    gemini jail and seat files, and the seat's own environment."""

    def __init__(self, copy: bytes, egress, *, extra_binds=()):
        self.copy, self.egress, self.extra_binds = copy, egress, list(extra_binds)
        self.base = Path(tempfile.mkdtemp(prefix="pl-p4e-"))
        self.tree = self.base / "review" / seat_jail.HOST_TREE_DIRNAME
        self.tree.mkdir(parents=True)
        (self.tree / "MARKER.txt").write_text("marker\n")
        self.seat_dir = self.base / "seat"
        self.seat_dir.mkdir(mode=0o700)

    def __enter__(self):
        self.lease = seat_uid.lease_seat_id(8)
        n = self.lease.__enter__()
        self.net = sandbox_egress.isolated_network(
            timeout_s=900, required=True, seat_uid_map=True, proxy_socket=self.egress.socket,
            proxy_port=seat_egress_proxy.SEAT_PROXY_PORT)
        egress = self.net.__enter__()
        self.token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        self.holder = seat_uid.holder_pid_from_prefix(egress)
        pi._write_gemini_config(self.seat_dir / seat_jail.HOST_GEMINI_CONFIG_DIRNAME, self.copy)
        ca = pi._write_egress_ca(self.seat_dir, self.egress.ca_cert)
        agy = Path(os.path.realpath(shutil.which("agy")))
        self.jail = seat_jail.build_seat_jail(
            "gemini", self.seat_dir, agy, tree=self.tree, bundle_memfd=seat_jail.memfd_with("b", b"B"),
            instructions_memfd=seat_jail.memfd_with("i", b"I"), seat_ids=(n, n),
            gemini_config=self.seat_dir / seat_jail.HOST_GEMINI_CONFIG_DIRNAME, egress_ca=ca,
            egress_proxy=self.egress.proxy_url)
        if self.extra_binds:
            owner = list(self.jail.process_owner)
            at = owner.index("--remount-ro")
            owner[at:at] = self.extra_binds
            object.__setattr__(self.jail, "process_owner", tuple(owner))
        else:
            pi._require_canonical_jail(self.jail)
        self.prefix = pi._compose_seat_jail_prefix(self.jail)
        return self

    def run(self, argv, timeout=300, input=None):
        for fd in self.jail.pass_fds:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
            except OSError:
                pass
        done = subprocess.run([*self.prefix, *argv], capture_output=True, text=True,
                              timeout=timeout, pass_fds=self.jail.pass_fds, env=pi._jail_launch_env(),
                              input=input, stdin=None if input is not None else subprocess.DEVNULL)
        secret = self.egress.proxy_url
        done.stdout = done.stdout.replace(secret, "<egress-proxy>")
        done.stderr = done.stderr.replace(secret, "<egress-proxy>")
        if "bwrap:" in done.stderr or "setpriv:" in done.stderr or "nsenter:" in done.stderr:
            raise SystemExit(f"probe harness failure: {done.stderr.strip()[-300:]}")
        return done

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


def curl(seat: Seat, url: str, *extra: str, proxy: bool = True) -> dict:
    """A real request from inside the seat. A refusal is told from a reply by who answered:
    a 403 to the CONNECT (only the proxy sees a CONNECT), a 403 inside the tunnel carrying the
    proxy's own tag (``X-Proxy-Error: blocked-by-sandbox-runtime``), or a TLS handshake the
    proxy ended after accepting the CONNECT; a ``real_reply`` is any status that is not one."""
    argv = ["/usr/bin/curl", "-sS", "--max-time", "15", "-o", "/dev/null", "-D", "-",
            "-w", "\nCODES %{http_code} %{http_connect}"]
    if not proxy:
        argv += ["--noproxy", "*"]
    done = seat.run([*argv, *extra, url], timeout=60)
    head, _, codes = done.stdout.rpartition("CODES ")
    code, _, connect = codes.strip().partition(" ")
    tagged = "x-proxy-error: blocked-by-sandbox-runtime" in head.lower()
    error = done.stderr.strip()[-200:]
    proxy_403 = connect == "403"
    filter_403 = code == "403" and tagged and connect == "200"
    tls_refused = code == "000" and connect == "200" and "SSL" in error
    return {"http_code": code, "connect_code": connect, "error": error, "proxy_tag": tagged,
            "refused_by_proxy": proxy_403 or tls_refused,
            "refused_by_request_filter": filter_403,
            "real_reply": code not in ("", "000") and not filter_403}


def body_of(seat: Seat, url: str, *extra: str) -> str:
    done = seat.run(["/usr/bin/curl", "-sS", "--max-time", "15", *extra, url], timeout=60)
    return done.stdout.strip()[:120]


def agy_turn(seat: Seat) -> dict:
    command = [*pi._jailed_gemini_command("gemini-3.8-flash-medium")]
    event = json.dumps({"event": "user", "message": {"content": TURN_PROMPT}}) + "\n"
    done = seat.run(command, timeout=300, input=event)
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    result = next((e.get("result") for e in events if e.get("event") == "result"), {}) or {}
    return {"status": result.get("status"), "response": result.get("response"),
            "event_types": sorted({e.get("event") for e in events})}


def ca_in_host_store(fingerprint: str) -> bool:
    try:
        text = HOST_TRUST_BUNDLE.read_text(encoding="ascii", errors="replace")
    except OSError:
        return False
    import hashlib

    for block in re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S):
        if hashlib.sha256(ssl.PEM_cert_to_DER_cert(block)).hexdigest() == fingerprint:
            return True
    return False


def proxy_env_keys(process) -> list[str]:
    raw = Path(f"/proc/{process.pid}/environ").read_bytes()
    return sorted(item.split(b"=", 1)[0].decode() for item in raw.split(b"\0") if item)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    record = {"schema": "seat_jail_probe_p4_containment_egress.v1", "issue": "agent-harness#1170",
              "ruling": "maintainer 'prove then enable', 2026-09-29; plan agent-harness#1244 S3/S4",
              "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "agy_version": subprocess.run(["agy", "--version"], capture_output=True, text=True).stdout.strip()}
    copy = seat_jail.build_gemini_seat_copy(OPERATOR)
    structure = staged_structure(copy)
    record["a_staged_copy"] = structure
    key = seat_egress_proxy.ca_paths()[1]
    extra_binds = (["--ro-bind", str(key), "/seat/egress-ca.key"]
                   if os.environ.get("PROBE_MUTATION") == "mount-ca-key" else [])
    with seat_egress_proxy.start_proxy() as egress:
        record["egress"] = seat_egress_proxy.egress_evidence(egress)
        record["s4"] = {
            "ca_in_host_trust_store": ca_in_host_store(egress.ca_sha256),
            "proxy_env_keys": proxy_env_keys(egress.process),
            "ca_dir_mode": oct(os.stat(seat_egress_proxy.ca_dir()).st_mode & 0o777),
            "ca_key_mode": oct(os.stat(key).st_mode & 0o777),
        }
        with Seat(copy, egress, extra_binds=extra_binds) as seat:
            turn = agy_turn(seat)
            copy_after = (seat.seat_dir / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
                          / "antigravity-oauth-token").read_bytes()
            token_files = seat.in_h(
                f"grep -rlE 'access_token|refresh_token' {seat.seat_dir}/seat-home "
                f"{seat.seat_dir}/seat-out 2>/dev/null | wc -l").strip()
            record["a_turn"] = {**turn, "staged_copy_unchanged": copy_after == copy,
                                "files_in_seat_writable_dirs_mentioning_a_token": int(token_files or 0)}
            record["a_token_refresh_endpoint"] = curl(
                seat, "https://oauth2.googleapis.com/token", "-X", "POST")
            record["b_inference_host"] = curl(
                seat, f"https://{INFERENCE}/v1internal:loadCodeAssist", "-X", "POST")
            record["b_inference_body_head"] = body_of(
                seat, f"https://{INFERENCE}/v1internal:loadCodeAssist", "-X", "POST")
            record["b_forbidden_hosts"] = {h: curl(seat, f"https://{h}/") for h in FORBIDDEN}
            record["b_forbidden_paths"] = {u: curl(seat, u) for u in FORBIDDEN_PATHS}
            record["b_tunnel_inner_host"] = curl(
                seat, f"https://{INFERENCE}/v1internal:loadCodeAssist", "-X", "POST",
                "-H", "Host: storage.googleapis.com")
            record["b_tunnel_inner_sni_and_host"] = curl(
                seat, "https://storage.googleapis.com/v1internal:loadCodeAssist", "-X", "POST",
                "--connect-to", f"storage.googleapis.com:443:{INFERENCE}:443")
            record["b_tunnel_inner_sni_only"] = curl(
                seat, "https://storage.googleapis.com/v1internal:loadCodeAssist", "-X", "POST",
                "-H", f"Host: {INFERENCE}",
                "--connect-to", f"storage.googleapis.com:443:{INFERENCE}:443")
            record["b_direct_without_proxy"] = {
                target: curl(seat, target, proxy=False)
                for target in ("https://1.1.1.1/", f"https://{INFERENCE}/")}
            record["s4"]["ca_key_visible_in_jail"] = seat.run(
                ["/bin/sh", "-c", "ls /seat; test -e /seat/egress-ca.key && echo KEY"]).stdout.count("KEY") > 0
            record["s4"]["trust_bundle_in_jail"] = seat.jail.env.get("SSL_CERT_FILE")
    expired = json.loads(copy)
    expired["token"]["expiry"] = "2020-01-01T00:00:00Z"
    with seat_egress_proxy.start_proxy() as egress, \
            Seat(json.dumps(expired).encode(), egress) as seat:
        record["a_expired_copy_turn"] = agy_turn(seat)["status"]

    stops = []
    if not record["b_inference_host"]["real_reply"]:
        raise SystemExit("control failed: no real reply from agy's inference host through the proxy")
    if structure["secret_keys_present"] or not structure["token_value_is_nonempty_string"]:
        stops.append("gemini_seat_credential_unusable: staged copy is not access-token-only")
    if record["a_turn"]["status"] != "SUCCESS":
        stops.append("gemini_seat_credential_unusable: agy does not run on the copy through the proxy")
    if (record["a_expired_copy_turn"] == "SUCCESS" or not record["a_turn"]["staged_copy_unchanged"]
            or record["a_turn"]["files_in_seat_writable_dirs_mentioning_a_token"]
            or not record["a_token_refresh_endpoint"]["refused_by_proxy"]):
        stops.append("gemini_seat_token_refreshed_in_jail")
    reached = [h for h, r in record["b_forbidden_hosts"].items() if not r["refused_by_proxy"]]
    reached += [u for u, r in record["b_forbidden_paths"].items()
                if not (r["refused_by_proxy"] or r["refused_by_request_filter"])]
    for row in ("b_tunnel_inner_host", "b_tunnel_inner_sni_and_host", "b_tunnel_inner_sni_only"):
        r = record[row]
        if not (r["refused_by_proxy"] or r["refused_by_request_filter"]):
            reached.append(row)
    reached += [t for t, r in record["b_direct_without_proxy"].items()
                if r["http_code"] not in ("", "000")]
    if reached:
        stops.append("gemini_seat_egress_unconfined: reached " + ", ".join(reached))
    s4 = record["s4"]
    if (s4["ca_in_host_trust_store"] or s4["ca_key_visible_in_jail"]
            or any(re.search(r"GOOGLE|GEMINI|AGY|TOKEN|PROXY|CREDENTIAL", k) for k in s4["proxy_env_keys"])
            or record["egress"].get("tls_inspection") is not True):
        stops.append("gemini_seat_egress_unconfined: S4 requirement not met")
    record["a_holds"] = not any("credential_unusable" in s or "refreshed" in s for s in stops)
    record["b_holds"] = not any("egress_unconfined: reached" in s for s in stops)
    record["s4_holds"] = not any("S4" in s for s in stops)
    record["stops"] = stops
    record["result"] = "stop" if stops else "pass"
    record["gemini_route_code"] = stops[0].split(":")[0] if stops else None
    summary = {k: record[k] for k in ("result", "stops", "a_holds", "b_holds", "s4_holds",
                                      "gemini_route_code")}
    print(json.dumps(summary, indent=1))
    if not check:
        OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return 0 if not stops else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
