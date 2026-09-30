#!/usr/bin/env python3
"""Mutation receipts for agent-harness#1132 (plan "Lanes": control green, named mutation red).

Each mutation is a literal text replacement applied to the REAL module path in this
checkout. For every mutation the named falsifier nodes are run twice: once on the
unmutated file (must pass) and once with the mutation applied (must fail). The original
bytes are restored from memory, never from git, and their digest is re-checked before the
next mutation. A mutation whose falsifier stays green is recorded as `survived` and fails
the run.

Usage (from the repo root): python3 plans/evidence/seat-jail-1132/run_mutation_receipts.py
Writes plans/evidence/seat-jail-1132/mutation-receipts.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "phase-loop-runtime"
SRC = RUNTIME / "src" / "phase_loop_runtime"
OUT = Path(__file__).resolve().parent / "mutation-receipts.json"

PI = SRC / "panel_invoker.py"
SJ = SRC / "seat_jail.py"
SU = SRC / "seat_uid.py"
SK = SRC / "seat_keyring_exec.py"
SE = SRC / "sandbox_egress.py"
VH = RUNTIME / "scripts" / "verify_harden_evidence.py"

T_JAIL = "tests/test_seat_jail.py"
T_PERM = "tests/test_seat_sandbox_permissions.py"
T_NOTE = "tests/test_seat_notices.py"
T_LIVE = "tests/test_seat_jail_live_d8.py"

MUTATIONS: list[dict[str, object]] = [
    {"id": "F030-drop-identity-literal", "file": PI,
     "old": '"seat_sandbox_refused:jail_build", "seat_sandbox_refused:namespace",\n    "seat_sandbox_refused:identity", "seat_sandbox_refused:jail_unqualified",',
     "new": '"seat_sandbox_refused:jail_build", "seat_sandbox_refused:namespace",\n    "seat_sandbox_refused:jail_unqualified",',
     "nodes": [f"{T_NOTE}::test_f030_every_notice_code_is_an_exact_detail_literal",
               f"{T_NOTE}::test_f030_leg_detail_equals_the_literal_after_finalize"]},
    {"id": "J14-remove-arch-rule", "file": SJ,
     "old": 'emit(_JEQ_K, _AUDIT_ARCH[arch], 0, "kill")', "new": 'emit(_JEQ_K, _AUDIT_ARCH[arch], 0, 0)',
     "nodes": [f"{T_JAIL}::test_j14_architecture_rule_kills_i386",
               f"{T_JAIL}::test_j14_live_i386_int80_is_killed"]},
    {"id": "J14-remove-x32-rule", "file": SJ,
     "old": 'emit(_JGE_K, X32_SYSCALL_BIT, "eperm", 0)', "new": 'emit(_JGE_K, X32_SYSCALL_BIT, 0, 0)',
     "nodes": [f"{T_JAIL}::test_j14_every_x32_number_is_eperm_before_per_syscall_rules"]},
    {"id": "J14-condition-setns-on-flags", "file": SJ,
     "old": 'emit(_JEQ_K, nr["setns"], "eperm", 0)', "new": 'emit(_JEQ_K, nr["setns"], "ns_flags", 0)',
     "nodes": [f"{T_JAIL}::test_j14_setns_is_eperm_even_with_nstype_zero"]},
    {"id": "J14-remove-af-alg-rule", "file": SJ,
     "old": 'emit(_JEQ_K, AF_ALG, "eperm", "allow")', "new": 'emit(_JEQ_K, AF_ALG, "allow", "allow")',
     "nodes": [f"{T_JAIL}::test_j14_af_alg_sockets_only", f"{T_JAIL}::test_j14_live_filter_denies_in_the_kernel"]},
    {"id": "J14-ioctl-compare-high-half", "file": SJ,
     "old": 'emit(_LD_W_ABS, _arg_low(1), label="ioctl")', "new": 'emit(_LD_W_ABS, _arg_low(1) + 4, label="ioctl")',
     "nodes": [f"{T_JAIL}::test_j14_tiocsti_and_tioclinux_compare_the_low_half_only"]},
    {"id": "J1-bind-home", "file": SJ,
     "old": '    for name in ETC_READONLY_SUBSET:\n        host = os.path.join("/etc", name)',
     "new": '    args += ["--ro-bind", str(Path.home()), str(Path.home())]\n    for name in ETC_READONLY_SUBSET:\n        host = os.path.join("/etc", name)',
     "nodes": [f"{T_JAIL}::test_j1_host_canaries_are_unreachable"]},
    {"id": "J2-drop-remount-ro", "file": SJ,
     "old": '        "--remount-ro", "/",\n', "new": "",
     "nodes": [f"{T_JAIL}::test_j2_writes_are_confined"]},
    {"id": "J3-drop-clearenv", "file": SJ,
     "old": '        "--clearenv",\n    ]', "new": "    ]",
     "nodes": [f"{T_JAIL}::test_j3_environment_is_exactly_the_declared_set"]},
    {"id": "J10-link-following-read", "file": SJ,
     "old": '_O_READ = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)',
     "new": '_O_READ = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)',
     "nodes": [f"{T_JAIL}::test_j10_refuses_every_unsafe_shape_without_blocking[symlink]"]},
    {"id": "J10-link-following-tree-walk", "file": SJ,
     "old": "            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)\n            if stat.S_ISLNK(info.st_mode):",
     "new": "            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=True)\n            if stat.S_ISLNK(info.st_mode):",
     "nodes": [f"{T_JAIL}::test_j10_rehash_equals_the_existing_revalidation"]},
    {"id": "J2-link-following-teardown", "file": SJ,
     "old": "    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)\n    if not stat.S_ISDIR(info.st_mode):\n        os.unlink(name, dir_fd=parent_fd)",
     "new": "    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=True)\n    if not stat.S_ISDIR(info.st_mode):\n        os.unlink(name, dir_fd=parent_fd)",
     "nodes": [f"{T_JAIL}::test_j2_teardown_never_follows_a_planted_link"]},
    {"id": "handoff-skip-nlink-check", "file": SU,
     "old": "            if not seat_jail.tree_is_private(tree_fd):", "new": "            if False:",
     "nodes": [f"{T_PERM}::test_handoff_refuses_a_hard_linked_stage_before_any_chown"]},
    {"id": "token-scan-disabled", "file": SJ,
     "old": "    return any(form in data for form in secret_encodings(secret))", "new": "    return False",
     "nodes": [f"{T_JAIL}::test_output_scan_finds_the_token_and_its_encodings_at_every_alignment"]},
    {"id": "token-file-mode-unchecked", "file": SJ,
     "old": "        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()\n                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > TOKEN_FILE_CAP_BYTES):",
     "new": "        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()\n                or info.st_size > TOKEN_FILE_CAP_BYTES):",
     "nodes": [f"{T_JAIL}::test_token_file_hygiene_refuses[loose-file]"]},
    {"id": "D7-keep-refresh-token", "file": SJ,
     "old": '    copy["token"] = {k: v for k, v in token.items() if k != "refresh_token"}',
     "new": '    copy["token"] = dict(token)',
     "nodes": [f"{T_JAIL}::test_d7_copy_strips_the_refresh_and_id_tokens"]},
    {"id": "J7-capability-before-step0", "file": SJ,
     "old": '    if not staged_tree_approved:\n        return SeatRoute(False, "seat_sandbox_not_staged")',
     "new": '    capable()\n    if not staged_tree_approved:\n        return SeatRoute(False, "seat_sandbox_not_staged")',
     "nodes": [f"{T_PERM}::test_j7_step0_no_tree_wins_and_evaluates_nothing_else"]},
    {"id": "J7-qualification-before-credential", "file": SJ,
     "old": "        if not (gemini_credential_present or gemini_operator_credential_present)():\n            return SeatRoute(False, \"gemini_seat_credential_missing\")\n",
     "new": "        if leg not in JAILED_LEGS:\n            return SeatRoute(False, \"gemini_seat_profile_unqualified\")\n        if not (gemini_credential_present or gemini_operator_credential_present)():\n            return SeatRoute(False, \"gemini_seat_credential_missing\")\n",
     "nodes": [f"{T_PERM}::test_j7_step3_credential_before_qualification_for_gemini"]},
    {"id": "EXECFIND-carry-unrecorded-digest", "file": PI,
     "old": "    if not (pass_recorded or _seat_jail.execfind_pass_recorded)(",
     "new": "    if False and not (pass_recorded or _seat_jail.execfind_pass_recorded)(",
     "nodes": [f"{T_PERM}::test_execfind_gate_refuses_an_unrecorded_digest_before_any_effect",
               f"{T_NOTE}::test_jailed_route_without_an_execfind_pass_is_refused_with_zero_launches"]},
    {"id": "keyring-shim-skipped", "file": SK,
     "old": "    try:\n        join_fresh_session_keyring()\n    except OSError as exc:",
     "new": "    try:\n        pass\n    except OSError as exc:",
     "nodes": [f"{T_JAIL}::test_keyring_shim_joins_a_fresh_session_keyring"]},
    {"id": "reap-any-owner", "file": SU,
     "old": "    if not owned_by_subordinate(owner, subuid=subuid):", "new": "    if False:",
     "nodes": [f"{T_NOTE}::test_reap_refuses_an_operator_owned_directory"]},
    {"id": "J8-accept-tooled-as-met", "file": VH,
     "old": "    if harden5_unmet(value):\n        fail(", "new": "    if False:\n        fail(",
     "nodes": [f"{T_PERM}::test_j8_verifier_reports_harden5_unmet_on_tooled_records"]},
    {"id": "notices-accept-str-subclass", "file": PI,
     "old": "                 if type(code) is str and code in _seat_jail.NOTICE_CODES)",
     "new": "                 if isinstance(code, str) and code in _seat_jail.NOTICE_CODES)",
     "nodes": [f"{T_NOTE}::test_cli_text_shaped_like_a_code_yields_no_notice"]},
    {"id": "D8-skip-bounding-set-drop", "file": SJ,
     "old": '"--clear-groups", "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all",',
     "new": '"--clear-groups", "--inh-caps=-all", "--ambient-caps=-all",',
     "nodes": [f"{T_PERM}::test_d8_prefix_order_replaces_the_1109_switch"]},
    {"id": "D8-holder-mapped-before-userns", "file": SE,
     "old": "                    _wait_for_new_user_namespace(holder)\n", "new": "",
     "nodes": [f"{T_PERM}::test_unmapped_holder_waits_for_its_map_then_yields_a_working_prefix"]},
    {"id": "J9-sealed-argv-drift", "file": PI,
     "old": '"--tools", "", "--allowedTools", "", "--disallowedTools",',
     "new": '"--tools", "default", "--allowedTools", "", "--disallowedTools",',
     "nodes": [f"{T_PERM}::test_j9_sealed_claude_argv_is_golden"]},
    {"id": "LIVE-handoff-skip-nlink-check", "file": SU,
     "old": "            if not seat_jail.tree_is_private(tree_fd):", "new": "            if False:",
     "nodes": [f"{T_LIVE}::test_handoff_live_refuses_a_hard_link_and_leaves_the_outside_file_alone"]},
    {"id": "LIVE-P5-no-cap-drop-all", "file": SJ,
     "old": '        "--cap-drop", "ALL",\n', "new": "",
     "nodes": [f"{T_LIVE}::test_live_pre_drop_set_is_exactly_the_three_capabilities"]},
    {"id": "LIVE-P1-tmpfs-not-sticky", "file": SJ,
     "old": '"--perms", "1777", "--tmpfs", "/tmp",', "new": '"--tmpfs", "/tmp",',
     "nodes": [f"{T_LIVE}::test_live_seat_can_use_tmp_etc_and_its_tree"]},
    {"id": "LIVE-P5-etc-not-traversable", "file": SJ,
     "old": '    args += ["--perms", "0755", "--dir", "/etc"]\n', "new": "",
     "nodes": [f"{T_LIVE}::test_live_seat_can_use_tmp_etc_and_its_tree"]},
    {"id": "LIVE-J4-shared-seat-uid", "file": SU,
     "old": "        try:\n            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)",
     "new": "        try:\n            n = 1  # mutation: every seat leases uid 1\n            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)",
     "nodes": [f"{T_LIVE}::test_j4_live_concurrent_seats_are_isolated"]},
    {"id": "R1-launch-refusal-code-dropped", "file": PI,
     "old": "        if type(exc) is _seat_jail.SeatSandboxRefused:\n",
     "new": "        if False:\n",
     "nodes": [f"{T_NOTE}::test_codex_r1_a_jailed_launch_refusal_keeps_its_code"]},
    {"id": "R1-transcript-written-before-scan", "file": PI,
     "old": "        if _seat_jail.contains_secret(data, seat.token):\n            token_seen.append(True)\n            data = b\"\"\n",
     "new": "        if _seat_jail.contains_secret(data, seat.token):\n            token_seen.append(True)\n",
     "nodes": [f"{T_NOTE}::test_codex_r1_no_parent_snapshot_ever_holds_the_token"]},
    {"id": "R1-monitor-not-forwarded", "file": PI,
     "old": "            transcript_refresh=_refresh_transcript,\n            **({\"review_monitor\": review_monitor} if review_monitor is not None else {}),\n",
     "new": "            transcript_refresh=_refresh_transcript,\n",
     "nodes": [f"{T_NOTE}::test_codex_r1_no_parent_snapshot_ever_holds_the_token"]},
    {"id": "R1-canonical-jail-unchecked", "file": PI,
     "old": "    if _seat_jail.actual_profile_digest(jail) != _seat_jail.jail_profile_digest(jail.leg):",
     "new": "    if False:",
     "nodes": [f"{T_PERM}::test_codex_r1_an_extra_bind_invalidates_the_qualified_digest",
               f"{T_PERM}::test_codex_r1_dropping_seccomp_invalidates_the_qualified_digest",
               f"{T_PERM}::test_codex_r1_the_installed_filter_bytes_are_checked_not_metadata",
               f"{T_PERM}::test_j6_test_only_filter_variant_is_refused_before_any_probe"]},
    {"id": "R1-mounts-derived-from-argv", "file": SJ,
     "old": "    for path in SYSTEM_READONLY_PATHS:\n        if os.path.isdir(path) and not os.path.islink(path):\n            points.add(path)\n",
     "new": "    for path in SYSTEM_READONLY_PATHS:\n        if os.path.isdir(path) and not os.path.islink(path):\n            points.add(path)\n    argv = list(jail.process_owner)\n    points.update(argv[i + 2] for i, a in enumerate(argv) if a == \"--bind\")\n",
     "nodes": [f"{T_PERM}::test_expected_mounts_do_not_follow_an_extra_bind"]},
    {"id": "R1-reap-maps-before-userns", "file": SU,
     "old": "        _wait_for_new_user_namespace(holder)\n        map_holder(holder.pid)",
     "new": "        map_holder(holder.pid)",
     "nodes": [f"{T_NOTE}::test_codex_r1_reap_namespace_is_mapped_only_after_it_exists"]},
    {"id": "R1-probe-accepts-inherited-seccomp", "file": SJ,
     "old": '"nested-userns-denied", fds,', "new": '"nested-userns-allowed", fds,',
     "nodes": [f"{T_LIVE}::test_j6_live_identity_probe_passes_through_the_production_prefix"]},
    {"id": "HANG-sealed-tui-cwd-drift", "file": PI,
     "old": "    tui_cwd = out_dir.resolve() if brokered else out_dir\n",
     "new": "    tui_cwd = out_dir.parent.resolve() if brokered else out_dir\n",
     "nodes": [f"{T_PERM}::test_hang_investigation_sealed_claude_tui_session_is_golden_to_main"]},
    {"id": "R2-behavioural-seccomp-check-deleted", "file": SJ,
     "edits": [("    '/usr/bin/unshare -U /bin/true 2>/dev/null && echo nested-userns-allowed '\n"
                "    '|| echo nested-userns-denied; '\n", ""),
               ('"nested-userns-denied", fds,', "fds,")],
     "nodes": [f"{T_LIVE}::test_r2_behavioural_check_refuses_a_filterless_jail_under_an_outer_filter"]},
    {"id": "R2-filter-count-check-deleted", "file": SJ,
     "edits": [("NoNewPrivs|Seccomp|Seccomp_filters):", "NoNewPrivs|Seccomp):"),
               ('"Seccomp:\\t2", f"Seccomp_filters:\\t{_own_seccomp_filters() + 1}",', '"Seccomp:\\t2",')],
     "nodes": [f"{T_LIVE}::test_r2_filter_count_refuses_a_filterless_jail"]},
    {"id": "R2-filter-count-read-from-group-leader", "file": SJ,
     "old": 'Path("/proc/thread-self/status")', "new": 'Path("/proc/self/status")',
     "nodes": [f"{T_LIVE}::test_r2_filter_count_refuses_a_filterless_jail"]},
    {"id": "R2-seccomp-offset-unchecked", "file": SJ,
     "old": "    if os.lseek(jail.seccomp_fd, 0, os.SEEK_CUR) != 0:\n",
     "new": "    if False:\n",
     "nodes": [f"{T_LIVE}::test_r2_seccomp_descriptor_must_be_at_offset_zero"]},
    {"id": "HOSTPASS-unsafe-record-accepted", "file": SJ,
     "old": "        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()\n                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > 64 * 1024):",
     "new": "        if (not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024):",
     "nodes": [f"{T_PERM}::test_a_foreign_or_unsafe_pass_record_is_no_pass"]},
    {"id": "HOSTPASS-gate-code-not-named", "file": PI,
     "old": '        return route, [], _seat_jail.refused("jail_unqualified")',
     "new": '        return route, [], _seat_jail.refused("identity")',
     "nodes": [f"{T_PERM}::test_a_host_layout_change_invalidates_the_recorded_pass",
               f"{T_NOTE}::test_jailed_route_without_an_execfind_pass_is_refused_with_zero_launches"]},
    {"id": "sealed-notice-dropped", "file": PI,
     "old": "    if not route.jailed:\n        return route, [str(route.code)], None",
     "new": "    if not route.jailed:\n        return route, [], None",
     "nodes": [f"{T_NOTE}::test_sealed_claude_seat_carries_its_notice_through_the_spawn"]},
]


def _run(nodes: list[str]) -> dict[str, object]:
    # A fresh bytecode cache per run: a same-length mutation written in the same second
    # as the original keeps its (mtime, size) and CPython would reuse the stale .pyc,
    # running the UNMUTATED module and reporting a false "survived" (or a false control).
    import tempfile

    cache = tempfile.mkdtemp(prefix="seat-jail-mutation-pyc-")
    env = {**os.environ, "PYTHONPATH": str(RUNTIME / "src"), "PYTHONPYCACHEPREFIX": cache,
           "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "-o", "addopts=", *nodes], cwd=RUNTIME, env=env,
                          capture_output=True, text=True, timeout=900)
    tail = [line for line in done.stdout.splitlines() if line.strip()][-1:] or [""]
    return {"returncode": done.returncode, "summary": tail[0]}


def main() -> int:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    receipts = []
    survived = []
    for mutation in MUTATIONS:
        path = Path(mutation["file"])
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        text = original.decode("utf-8")
        # One mutation may need several literal edits (a check and its expectation).
        edits = list(mutation.get("edits") or [(mutation["old"], mutation["new"])])
        mutated_text = text
        for old, new in edits:
            if mutated_text.count(old) != 1:
                raise SystemExit(f"{mutation['id']}: mutation anchor matches {mutated_text.count(old)} times")
            mutated_text = mutated_text.replace(old, new, 1)
        old, new = "\n".join(e[0] for e in edits), "\n".join(e[1] for e in edits)
        control = _run(list(mutation["nodes"]))
        try:
            path.write_text(mutated_text, encoding="utf-8")
            mutated = _run(list(mutation["nodes"]))
        finally:
            path.write_bytes(original)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"{mutation['id']}: restore failed")
        ok = control["returncode"] == 0 and mutated["returncode"] != 0
        if not ok:
            survived.append(mutation["id"])
        receipts.append({
            "id": mutation["id"],
            "file": str(path.relative_to(ROOT)),
            "file_sha256": digest,
            "mutation": {"old": old, "new": new},
            "nodes": mutation["nodes"],
            "control": control,
            "mutated": mutated,
            "result": "red_as_required" if ok else "survived",
        })
        print(f"{mutation['id']}: {receipts[-1]['result']}", flush=True)
    OUT.write_text(json.dumps({"schema": "seat_jail_mutation_receipts.v1", "head": head,
                               "issue": "agent-harness#1132", "receipts": receipts,
                               "survived": survived}, indent=2) + "\n", encoding="utf-8")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
