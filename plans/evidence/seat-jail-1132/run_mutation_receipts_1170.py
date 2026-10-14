#!/usr/bin/env python3
"""Mutation receipts for agent-harness#1170 (the jailed Gemini seat's egress layer).

Each mutation is a literal text replacement applied to the REAL file in this checkout, or,
for the two S4 host-state rows, a probe input. A ``test`` mutation runs its named test nodes
on the unmutated file (must pass) and mutated (must fail). A ``probe`` mutation runs the live
containment probe (probe_p4_containment_egress.py --check) mutated, and must turn it red FOR
THE NAMED REASON: the expected stop text must appear, or the runtime must refuse before a
seat runs (``refused_by_runtime``). A red for any other reason -- an expired login, say -- is
not a receipt. The original bytes are restored from memory and re-checked by digest.

Usage (from the repo root): python3 plans/evidence/seat-jail-1132/run_mutation_receipts_1170.py
    [--only ID ...]
Writes plans/evidence/seat-jail-1132/mutation-receipts-1170.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "phase-loop-runtime"
SRC = RUNTIME / "src" / "phase_loop_runtime"
OUT = Path(__file__).resolve().parent / "mutation-receipts-1170.json"
PROBE = Path(__file__).resolve().parent / "probe_p4_containment_egress.py"
PYTHON = sys.executable

SJ, SE, PI = SRC / "seat_jail.py", SRC / "sandbox_egress.py", SRC / "panel_invoker.py"
EP = SRC / "seat_egress_proxy.py"
MJS = SRC / "seat_egress" / "proxy.mjs"
ALLOW = SRC / "seat_egress" / "gemini-allowlist.json"
T = "tests/test_gemini_seat_egress_1170.py"

WIDEN = ('    {"host": "lh3.googleusercontent.com", "port": 443, "method": "GET", "path_prefix": "/a/"}\n',
         '    {"host": "lh3.googleusercontent.com", "port": 443, "method": "GET", "path_prefix": "/a/"},\n'
         '    {"host": "storage.googleapis.com", "port": 443, "method": "GET", "path_prefix": "/"}\n')
OPEN_RULES = ('        "-A OUTPUT -j REJECT",\n        "-P OUTPUT DROP",\n',
              '        "-A OUTPUT -j ACCEPT",\n        "-P OUTPUT ACCEPT",\n')
UPLINK = ("            if proxy_socket is not None:\n                pass  # no uplink",
          "            if False:\n                pass  # no uplink")
NO_BRIDGE_CHECK = ("                if not _proxy_bridge_confines(prefix, helpers[\"python3\"], proxy_port):",
                   "                if False:")
NO_HOST_CHECK = ("  if (!innerHost(request, url)) {", "  if (false) {")
NO_SNI_CHECK = ("if (config.inner_sni_check) {", "if (false) {")
# grok-A: neutralise the front's behaviour (splice a non-ClientHello first flight to srt,
# which then opaque-tunnels it) instead of refusing it. Not a string deletion.
FRONT_FORWARDS_ANYTHING = (
    "      client.destroy(); // not a positively-inspected allowed-SNI ClientHello: no bytes upstream",
    "      phase = 'spliced'; spliceToSrt(client, target, buf); // neutralised guard")
# both SNI walls: the front's allow-check and srt's SNICallback hook.
FRONT_ANY_SNI = ("    if (sni && hosts.has(sni)) {", "    if (sni) {")

MUTATIONS: list[dict[str, object]] = [
    # -- live probe rows -------------------------------------------------------------------
    {"id": "probe-widen-allowlist", "kind": "probe", "edits": [(ALLOW, *WIDEN)],
     "expect": "reached storage.googleapis.com"},
    {"id": "probe-direct-egress", "kind": "probe",
     "edits": [(SE, *OPEN_RULES), (SE, *UPLINK)], "expect": "refused_by_runtime"},
    {"id": "probe-direct-egress-past-the-bridge-check", "kind": "probe",
     "edits": [(SE, *OPEN_RULES), (SE, *UPLINK), (SE, *NO_BRIDGE_CHECK)],
     "expect": "reached https://1.1.1.1/"},
    {"id": "probe-skip-inner-host-check", "kind": "probe", "edits": [(MJS, *NO_HOST_CHECK)],
     "expect": "reached b_tunnel_inner_host"},
    {"id": "probe-fail-closed-front-neutralised", "kind": "probe", "edits": [(MJS, *FRONT_FORWARDS_ANYTHING)],
     "expect": "reached attack_0x04_record_sni_storage"},
    # NOTE: there is deliberately no SNI-wall probe mutation. On srt's terminated path the
    # upstream is the CONNECT target regardless of the inner SNI, so neutralising the SNI
    # checks (front allow-check + srt SNICallback hook) does not reach a non-allowlisted
    # service: a trial mutation of both SURVIVED, confirming the SNI wall is defense-in-depth,
    # not the load-bearing control. The load-bearing control against SNI cross-routing is the
    # fail-closed front keeping srt on the terminated path (probe-fail-closed-front-neutralised,
    # which reds). The president KEPT the SNI hook and deferred its behavioural coverage
    # (claude-sni-not-pinned, follow-up).
    {"id": "probe-drop-tls-evidence", "kind": "probe",
     "edits": [(EP, '        "tls_inspection": True,\n', "")], "expect": "S4 requirement not met"},
    {"id": "probe-mount-ca-key", "kind": "probe", "edits": [], "env": {"PROBE_MUTATION": "mount-ca-key"},
     "expect": "S4 requirement not met"},
    {"id": "probe-trust-ca-in-host-store", "kind": "probe", "edits": [], "host_bundle_with_ca": True,
     "expect": "S4 requirement not met"},
    # -- unit tests ------------------------------------------------------------------------
    {"id": "route-skip-egress-check", "kind": "test",
     "edits": [(SJ, "        if reason is not None:\n            _LOG.warning(\"seat gemini: egress",
                "        if False:\n            _LOG.warning(\"seat gemini: egress")],
     "nodes": [f"{T}::test_without_its_egress_layer_the_gemini_seat_is_degraded_never_sealed",
               f"{T}::test_the_spawn_refuses_a_gemini_seat_without_its_egress_layer"]},
    {"id": "rules-open", "kind": "test", "edits": [(SE, *OPEN_RULES)],
     "nodes": [f"{T}::test_the_proxy_only_rules_admit_one_loopback_port_and_nothing_else"]},
    {"id": "allowlist-widened", "kind": "test", "edits": [(ALLOW, *WIDEN)],
     "nodes": [f"{T}::test_the_allowlist_is_the_measured_request_set"]},
    {"id": "install-skip-tree-digest", "kind": "test",
     "edits": [(EP, "        if tree_sha256(modules) != SRT_TREE_SHA256:", "        if False:")],
     "nodes": [f"{T}::test_verify_install_accepts_the_pinned_tree_and_refuses_a_changed_file"]},
    {"id": "ca-skip-owner-only", "kind": "test",
     "edits": [(EP, "    if stat.S_IMODE(info.st_mode) & 0o077:\n        return \"not 0700\"",
                "    if False:\n        return \"not 0700\"")],
     "nodes": [f"{T}::test_the_ca_must_be_owner_only"]},
    {"id": "stream-accepts-subagent", "kind": "test",
     "edits": [(PI, '_JAILED_GEMINI_STEP_TYPES = frozenset({"user_input", "agent_response", "tool"})',
                '_JAILED_GEMINI_STEP_TYPES = frozenset({"user_input", "agent_response", "tool", "subagent"})'),
               (PI, ' not in _JAILED_GEMINI_STEP_TYPES or "subagent_info" in step:',
                ' not in _JAILED_GEMINI_STEP_TYPES:')],
     "nodes": [f"{T}::test_a_subagent_or_unrecorded_step_ends_the_tooled_leg"]},
    {"id": "token-guard-off", "kind": "test",
     "edits": [(PI, "            token_seen.append(True)\n            return True\n        seen[0]",
                "            return False\n        seen[0]")],
     "nodes": [f"{T}::test_a_token_split_across_chunks_is_caught_before_it_is_kept"]},
    {"id": "config-ancestor-not-bound", "kind": "test",
     # F006 structural: binding only antigravity-cli (not the ancestor .gemini) is the
     # pre-fix shape the seat could rename around; the canonical-digest guard refuses it at
     # launch, and the bind test catches it here. The live falsifier is the probe's
     # config_ancestor_check row (p4-containment-egress.json f006_config_ancestor).
     "edits": [(SJ, '    binds = ["--ro-bind", gemini_config, SEAT_GEMINI_DOTDIR]',
                '    binds = ["--ro-bind", gemini_config + "/antigravity-cli", SEAT_GEMINI_CONFIG]')],
     "nodes": [f"{T}::test_the_gemini_jail_binds_its_config_read_only_and_only_the_measured_dirs_writable"]},
    {"id": "install-skip-symlink-check", "kind": "test",
     "edits": [(EP, "        reject_unexpected_symlinks(modules)\n", "        pass  # symlink check removed\n")],
     "nodes": [f"{T}::test_verify_install_rejects_a_symlink_shadow_outside_bin"]},
    {"id": "proxy-token-not-scanned", "kind": "test",
     "edits": [(PI, '    if password:\n        secrets.append(password.encode("utf-8"))',
                '    if password and False:\n        secrets.append(password.encode("utf-8"))')],
     "nodes": [f"{T}::test_the_proxy_session_token_in_the_output_ends_the_leg",
               f"{T}::test_both_seat_secrets_are_scanned"]},
    {"id": "tree-made-a-workspace", "kind": "test",
     "edits": [(PI, '        "--disable-slash-commands", "--input-format", "stream-json",\n        "--output-format", "stream-json", "--print=", "--print-timeout", "0",\n    ]',
                '        "--disable-slash-commands", "--input-format", "stream-json",\n        "--output-format", "stream-json", "--print=", "--print-timeout", "0",\n        "--add-dir", _seat_jail.SEAT_TREE,\n    ]')],
     "nodes": [f"{T}::test_the_jailed_argv_makes_no_workspace_of_the_tree"]},
    {"id": "proxy-url-unredacted", "kind": "test",
     "edits": [(SJ, "            if self.egress_proxy and item == self.egress_proxy:",
                "            if False:")],
     "nodes": [f"{T}::test_per_launch_egress_values_do_not_move_the_qualified_digest"]},
    {"id": "qualification-seat-jailed", "kind": "test",
     "edits": [(PI, '    if leg == "gemini" and gemini_heartbeat._CANDIDATE is not None:\n        # The agy self-qualification',
                '    if False:\n        # The agy self-qualification')],
     "nodes": [f"{T}::test_the_agy_qualification_worker_keeps_its_gemini_seat_on_the_heartbeat_route"]},
    {"id": "evidence-drops-tls-inspection", "kind": "test",
     "edits": [(EP, '        "tls_inspection": True,\n', "")],
     "nodes": [f"{T}::test_the_egress_evidence_records_tls_inspection"]},
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _login_left() -> float:
    done = subprocess.run([PYTHON, "-c", "from phase_loop_runtime import panel_invoker as pi;"
                           "from pathlib import Path;print(pi._gemini_login_left_s(Path.home()) or 0)"],
                          capture_output=True, text=True, cwd=RUNTIME / "src")
    return float(done.stdout.strip() or 0)


def _fresh_login() -> None:
    """agy renews only an expired login: wait for expiry, then renew it outside any seat."""
    left = _login_left()
    if left > 600:
        return
    while left > 0:
        time.sleep(min(left + 2, 30))
        left = _login_left()
    subprocess.run(["agy", "models"], cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
                   capture_output=True, timeout=120,
                   env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/dev/null"})


def _probe(env_extra: dict[str, str]) -> dict[str, object]:
    _fresh_login()
    done = subprocess.run([PYTHON, str(PROBE), "--check"], capture_output=True, text=True,
                          env={**os.environ, **env_extra}, timeout=1800, cwd=ROOT)
    return {"returncode": done.returncode, "stdout": done.stdout[-1500:], "stderr": done.stderr[-600:]}


def _tests(nodes) -> dict[str, object]:
    done = subprocess.run([PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes],
                          capture_output=True, text=True, cwd=RUNTIME, timeout=900)
    tail = [line for line in done.stdout.splitlines() if " passed" in line or " failed" in line]
    return {"returncode": done.returncode, "summary": tail[-1] if tail else done.stdout[-300:]}


def main(argv: list[str]) -> int:
    only = set(argv[argv.index("--only") + 1:]) if "--only" in argv else None
    receipts = json.loads(OUT.read_text())["receipts"] if (only and OUT.exists()) else []
    receipts = [r for r in receipts if not only or r["id"] not in only]
    for mutation in MUTATIONS:
        if only and mutation["id"] not in only:
            continue
        originals = {}
        for path, old, _new in mutation["edits"]:
            data = originals.setdefault(path, path.read_bytes())
            if data.decode().count(old) != 1:
                raise SystemExit(f"{mutation['id']}: anchor not unique in {path}")
        receipt: dict[str, object] = {
            "id": mutation["id"], "kind": mutation["kind"],
            "edits": [{"file": str(p.relative_to(ROOT)), "file_sha256": _sha(originals[p]),
                       "old": old, "new": new} for p, old, new in mutation["edits"]],
        }
        env_extra = dict(mutation.get("env", {}))
        bundle = None
        if mutation.get("host_bundle_with_ca"):
            from_ca = (Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
                       / "phase-loop" / "seat-egress-ca" / "ca.crt")
            bundle = Path(tempfile.mkdtemp()) / "bundle.crt"
            bundle.write_text(Path("/etc/ssl/certs/ca-certificates.crt").read_text() + from_ca.read_text())
            env_extra["PROBE_HOST_TRUST_BUNDLE"] = str(bundle)
            receipt["probe_input"] = "PROBE_HOST_TRUST_BUNDLE = the host bundle plus the seat CA"
        if env_extra and "PROBE_HOST_TRUST_BUNDLE" not in env_extra:
            receipt["probe_input"] = env_extra
        if mutation["kind"] == "test":
            receipt["nodes"] = mutation["nodes"]
            receipt["control"] = _tests(mutation["nodes"])
        try:
            for path, old, new in mutation["edits"]:
                path.write_bytes(path.read_bytes().replace(old.encode(), new.encode(), 1))
            if mutation["kind"] == "test":
                receipt["mutated"] = _tests(mutation["nodes"])
                red = receipt["control"]["returncode"] == 0 and receipt["mutated"]["returncode"] != 0
            else:
                receipt["mutated"] = run = _probe(env_extra)
                expect = mutation["expect"]
                if expect == "refused_by_runtime":
                    red = run["returncode"] not in (0, 3) and (
                        "EgressUnavailable" in run["stderr"] or "bridge does not answer" in run["stderr"])
                else:
                    red = run["returncode"] == 3 and expect in run["stdout"]
                receipt["expected_reason"] = expect
        finally:
            for path, data in originals.items():
                path.write_bytes(data)
                assert _sha(path.read_bytes()) == _sha(data)
        receipt["result"] = "red_as_required" if red else "SURVIVED"
        print(mutation["id"], receipt["result"], flush=True)
        receipts.append(receipt)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    order = [m["id"] for m in MUTATIONS]
    receipts.sort(key=lambda r: order.index(r["id"]))
    OUT.write_text(json.dumps({"schema": "seat_jail_mutation_receipts.v1", "issue": "agent-harness#1170",
                               "head": head, "receipts": receipts}, indent=2) + "\n")
    survived = [r["id"] for r in receipts if r["result"] != "red_as_required"]
    print("survived:", survived)
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
