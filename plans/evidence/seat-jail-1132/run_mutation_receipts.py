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
SQ = SRC / "seat_jail_qualification.py"
SC = SRC / "seat_credentials.py"
SA = SRC / "seat_jail_autoqualify.py"
T_AQ = "tests/test_seat_jail_autoqualify.py"
CONFTEST = RUNTIME / "tests" / "conftest.py"
T_CRED = "tests/test_seat_credentials.py"
GR = SRC / "governed_review.py"
CL = SRC / "cli.py"
T_AGY = "tests/test_agy_canary_evidence.py"

UPG_NODE = (f"{T_PERM}::test_upg_every_other_group_writable_chain_refuses_with_the_chmod_notice"
            "[%s]")
R5_NODES = [f"{T_PERM}::test_codex_r5_hostile_records_refuse_typed_through_the_gate[%s]" % shape
               for shape in ("nul-in-evidence-name", "unpaired-surrogate", "non-string-evidence", "huge-integer")]

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
     "old": "    refusal = _pass_refusal(_seat_jail.jail_profile_digest(leg), pass_recorded)\n",
     "new": "    refusal = None\n",
     "nodes": [f"{T_PERM}::test_execfind_gate_refuses_an_unrecorded_digest_before_any_effect"]},
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
    {"id": "HOSTPASS-gate-code-not-named", "file": PI,
     "old": '    sub = "pass_store_unsafe" if reason.startswith("store_unsafe:") else "jail_unqualified"',
     "new": '    sub = "pass_store_unsafe" if reason.startswith("store_unsafe:") else "identity"',
     "nodes": [f"{T_PERM}::test_codex_r5_the_exception_class_reaches_the_launch_refusal_and_the_log"]},
    {"id": "R4-evidence-not-rehashed", "file": SJ,
     "old": "    if evidence_bytes is None or hashlib.sha256(evidence_bytes).hexdigest() != evidence_sha:\n        return False, \"evidence_mismatch\"\n",
     "new": "    if evidence_bytes is None:\n        return False, \"evidence_mismatch\"\n",
     "nodes": [f"{T_PERM}::test_codex_r4_a_stale_record_is_no_pass"]},
    {"id": "R4-host-not-bound", "file": SJ,
     "old": '"host_identity": host, "falsifier_layout": layout}\n    if any(',
     "new": '"falsifier_layout": layout}\n    if any(',
     "nodes": [f"{T_PERM}::test_codex_r4_another_hosts_record_is_no_pass"]},
    {"id": "R4-evidence-optional", "file": SJ,
     "old": "    if not isinstance(evidence_name, str) or not isinstance(evidence_sha, str):\n        return False, \"evidence_mismatch\"\n",
     "new": "    if not isinstance(evidence_name, str) or not isinstance(evidence_sha, str):\n        return True, \"pass\"\n",
     "nodes": [f"{T_PERM}::test_codex_r4_a_hand_written_pass_without_evidence_is_no_pass"]},
    {"id": "R4-blocking-open", "file": SJ,
     "old": '    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)\n',
     "new": '    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)\n',
     "nodes": [f"{T_PERM}::test_codex_r4_unsafe_records_give_a_typed_refusal_in_bounded_time[fifo]"]},
    {"id": "R4-parent-chain-unchecked", "file": SJ,
     "old": "        if problem is not None:\n            return False, f\"store_unsafe:{problem}:{directory}\"\n",
     "new": "        if False:\n            return False, \"\"\n",
     "nodes": [f"{T_PERM}::test_codex_r4_an_unsafe_parent_directory_is_no_pass"]},
    {"id": "R4-launch-not-requalified", "file": PI,
     "old": "    refusal = _pass_refusal(_seat_jail.actual_profile_digest(jail), pass_recorded)\n",
     "new": "    refusal = None\n",
     "nodes": [f"{T_PERM}::test_codex_r4_a_digest_change_between_gate_and_launch_is_refused"]},
    {"id": "R4-record-owner-unchecked", "file": SJ,
     "old": "        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()\n                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > cap):",
     "new": "        if (not stat.S_ISREG(info.st_mode)\n                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > cap):",
     "nodes": [f"{T_LIVE}::test_r4_live_a_record_owned_by_a_seat_uid_is_no_pass"]},
    {"id": "Q-mount-check-disabled", "file": SQ,
     "old": "                          if (m[1], m[2]) in protected_ids | protected_file_ids | ancestors]",
     "new": "                          if False]",
     "nodes": [f"{T_LIVE}::test_execfind2_jail_falsifiers_catch_a_jail_that_exposes_the_run"]},
    {"id": "Q-layout-ignores-system-roots", "file": SJ,
     "old": "    parts += [repr(review_stage._FALSIFIER_SYSTEM_ROOTS), repr(review_stage._FALSIFIER_PYTHON_FLAGS),",
     "new": "    parts += [repr(review_stage._FALSIFIER_PYTHON_FLAGS),",
     "nodes": [f"{T_PERM}::test_the_falsifier_layout_identity_follows_execfind_staging"]},
    {"id": "L4b-governed-notices-dropped", "file": GR,
     "old": "        for notice in getattr(leg, \"seat_notices\", ()):\n",
     "new": "        for notice in ():\n",
     "nodes": [f"{T_NOTE}::test_governed_surface_renders_every_notice"]},
    {"id": "R5-boundary-narrowed-to-oserror", "file": SJ,
     "old": "    except Exception as exc:\n        _LOG.warning(\"seat jail pass record rejected: %s\", type(exc).__name__)",
     "new": "    except OSError as exc:\n        _LOG.warning(\"seat jail pass record rejected: %s\", type(exc).__name__)",
     "nodes": R5_NODES},
    {"id": "R5-boundary-removed", "file": SJ,
     "old": "    try:\n        return _evaluate_pass_record(profile_digest, root=root, layout=layout, host=host)\n    except Exception as exc:\n        _LOG.warning(\"seat jail pass record rejected: %s\", type(exc).__name__)\n        return False, f\"error:{type(exc).__name__}\"\n",
     "new": "    return _evaluate_pass_record(profile_digest, root=root, layout=layout, host=host)\n",
     "nodes": R5_NODES},
    {"id": "CI-closer-closes-nothing", "file": SJ,
     "old": '    "  try: os.close(fd)\\n"\n',
     "new": '    "  try: pass\\n"\n',
     "nodes": [f"{T_JAIL}::test_j3_the_closer_closes_a_leaked_descriptor"]},
    {"id": "CI-closer-dropped-from-launch-prefix", "file": PI,
     "old": '        *_seat_jail.seat_fd_closer("" if jail.token_fd is None else str(jail.token_fd)),\n',
     "new": "",
     "nodes": [f"{T_PERM}::test_d8_prefix_order_replaces_the_1109_switch"]},
    {"id": "CI-capture-keeps-notices", "file": CL,
     "old": "capture=capture, basename=private_board_name, payload=capture_payload",
     "new": "capture=capture, basename=private_board_name, payload=payload",
     "nodes": [f"{T_AGY}::test_advisor_board_cli_seals_and_verifies_capture_summary"]},
    {"id": "R5-reason-drops-the-class", "file": SJ,
     "old": '        return False, f"error:{type(exc).__name__}"\n',
     "new": '        return False, "error"\n',
     "nodes": [f"{T_PERM}::test_codex_r5_the_exception_class_reaches_the_launch_refusal_and_the_log"]},
    {"id": "UPG-no-exception-strict-0700", "file": SJ,
     "old": "    if mode & 0o020 and not _operator_private_group(info.st_gid):\n",
     "new": "    if mode & 0o020:\n",
     "nodes": [f"{T_PERM}::test_upg_a_group_writable_chain_in_the_operators_private_group_qualifies"]},
    {"id": "UPG-primary-gid-unchecked", "file": SJ,
     "old": "    if gid != me.pw_gid:\n        return False\n",
     "new": "    if False:\n        return False\n",
     "nodes": [UPG_NODE % "not-the-primary-gid"]},
    {"id": "UPG-group-name-unchecked", "file": SJ,
     "old": "    if group.gr_name != me.pw_name or any(",
     "new": "    if any(",
     "nodes": [UPG_NODE % "group-named-otherwise"]},
    {"id": "UPG-other-members-unchecked", "file": SJ,
     "old": " or any(m != me.pw_name for m in group.gr_mem):\n",
     "new": " or False:\n",
     "nodes": [UPG_NODE % "group-has-another-member"]},
    {"id": "UPG-other-primary-unchecked", "file": SJ,
     "old": "    return not any(acct.pw_gid == gid and acct.pw_uid != me.pw_uid for acct in getpwall())\n",
     "new": "    return True\n",
     "nodes": [UPG_NODE % "another-accounts-primary"]},
    {"id": "UPG-no-database-accepts", "file": SJ,
     "old": "    if db is None:\n        return False\n",
     "new": "    if db is None:\n        return True\n",
     "nodes": [UPG_NODE % "no-account-database"]},
    {"id": "UPG-other-writable-allowed", "file": SJ,
     "old": '    if mode & 0o002:\n        return "other_writable"\n',
     "new": "",
     "nodes": [UPG_NODE % "other-writable"]},
    {"id": "UPG-store-code-collapsed", "file": PI,
     "old": '    sub = "pass_store_unsafe" if reason.startswith("store_unsafe:") else "jail_unqualified"',
     "new": '    sub = "jail_unqualified"',
     "nodes": [UPG_NODE % "group-has-another-member"]},
    {"id": "UPG-recorder-own-rule", "file": SQ,
     "old": "            if seat_jail.pass_store_dir_problem(directory) is not None:\n",
     "new": "            if False:\n",
     "nodes": [f"{T_PERM}::test_upg_the_recorder_accepts_the_private_group_and_refuses_a_shared_one"]},
    {"id": "sealed-notice-dropped", "file": PI,
     "old": "    if not route.jailed:\n        return route, [str(route.code)], None",
     "new": "    if not route.jailed:\n        return route, [], None",
     "nodes": [f"{T_NOTE}::test_sealed_claude_seat_carries_its_notice_through_the_spawn"]},
    # Merge with agent-harness#1204: the pointer-brief preflight notices are appended to
    # the seat notices; replacing them (main's pre-merge shape) must turn the test red.
    {"id": "merge-preflight-replaces-seat-notices", "file": CL,
     "old": 'payload["notices"] += [n.as_json() for n in result.seat_preflight_notices]',
     "new": 'payload["notices"] = [n.as_json() for n in result.seat_preflight_notices]',
     "nodes": ["tests/test_seat_preflight_1204.py::"
               "test_cli_pointer_brief_keeps_the_seat_notices_beside_the_preflight_notices"]},
    # The jailed route is Claude-only: a Gemini leg passing step 4 must turn the pin red.
    {"id": "gemini-passes-step4", "file": SJ,
     "old": "if leg not in JAILED_LEGS or gemini_qualified is None or not gemini_qualified():",
     "new": "if gemini_qualified is None or not gemini_qualified():",
     "nodes": [f"{T_PERM}::test_j7_the_jailed_route_is_claude_only[gemini]"]},
    # Seat-token rotation and the rate-limited token notice (maintainer addendum, 2026-10-03).
    {"id": "token-notice-dropped", "file": PI,
     "old": '                seat.notices.append("claude_seat_login_rate_limited" if login\n                                    else "claude_seat_token_rate_limited")',
     "new": '                pass',
     "nodes": [f"{T_NOTE}::test_a_rate_limited_seat_token_ends_the_leg_with_its_own_notice"]},
    {"id": "jailed-tail-unclassified", "file": PI,
     "old": "        failure = _leg_failure_detail(status, rc, review_text, pty_tail)",
     "new": "        failure = None",
     "nodes": [f"{T_NOTE}::test_a_rate_limited_seat_token_ends_the_leg_with_its_own_notice"]},
    {"id": "jailed-tail-not-scanned", "file": PI,
     "old": "            or _seat_jail.contains_secret(pty_tail.encode(\"utf-8\", errors=\"replace\"), seat.token)):",
     "new": "            ):",
     "nodes": [f"{T_NOTE}::test_the_pty_tail_is_scanned_for_the_seat_token"]},
    {"id": "limit-predicate-drops-1194-class", "file": SJ,
     "old": '"usage_limit", "claude_seat_rate_limited", "claude_seat_usage_limited",',
     "new": '"usage_limit", "claude_seat_rate_limited",',
     "nodes": [f"{T_NOTE}::test_limit_details_are_recognised_exactly"]},
    {"id": "seat-token-file-cached", "file": SJ,
     "old": "    token = data.strip()\n    if not token or len(data) > TOKEN_FILE_CAP_BYTES",
     "new": "    token = globals().setdefault(\"_TOKEN_CACHE\", data.strip())\n    if not token or len(data) > TOKEN_FILE_CAP_BYTES",
     "nodes": [f"{T_PERM}::test_the_seat_token_is_read_afresh_after_an_atomic_replace",
               f"{T_PERM}::test_each_jailed_leg_launches_with_the_token_current_at_its_launch"]},
    {"id": "seat-token-cached-per-process", "file": PI,
     "old": "    token = credential.token\n",
     "new": "    token = globals().setdefault(\"_SEAT_TOKEN\", credential.token)\n",
     "nodes": [f"{T_PERM}::test_each_jailed_leg_launches_with_the_token_current_at_its_launch"]},
    # The pointer-brief preflight reads the jailed route (team-lead ruling, 2026-10-03).
    {"id": "preflight-ignores-the-jail", "file": PI,
     "old": "        return sandbox_usable_by(leg, brokered, jailed=bool(leg and jailed_by_leg[leg]))",
     "new": "        return sandbox_usable_by(leg, brokered)",
     "nodes": ["tests/test_seat_preflight_1204.py::test_a_jailed_claude_seat_is_not_marked_unreadable[True-unreadable0]"]},
    {"id": "A2-failed-qualification-still-jails", "file": PI,
     "old": "    return _seat_jail.SeatRoute(False, sealed), [sealed], None",
     "new": "    return route, [sealed], None",
     "nodes": ["tests/test_seat_preflight_1204.py::test_a_jailed_claude_seat_is_not_marked_unreadable[False-unreadable1]",
               f"{T_NOTE}::test_a_jail_whose_first_use_qualification_fails_runs_sealed_never_refused"]},
    {"id": "token-rejected-notice-dropped", "file": PI,
     "old": '                    seat.notices.append("claude_seat_login_rejected" if login\n                                        else "claude_seat_token_rejected")',
     "new": '                    pass',
     "nodes": [f"{T_NOTE}::test_a_rejected_seat_token_ends_the_leg_with_its_notice"]},
    # Plan amendment A1: the login credential, its margin, the modes and the outcomes.
    {"id": "A1-override-loses-precedence", "file": SC,
     "old": "    if override_present():\n        return SeatCredential(",
     "new": "    if False:\n        return SeatCredential(",
     "nodes": [f"{T_CRED}::test_an_override_takes_precedence_over_the_login"]},
    {"id": "A1-no-margin-check", "file": SC,
     "old": "    if login.expires_at is not None and login.expires_at - now() < margin_s:\n        refresh()",
     "new": "    if False:\n        refresh()",
     "nodes": [f"{T_CRED}::test_a_short_login_is_refreshed_through_the_cli_then_reread",
               f"{T_CRED}::test_a_login_still_short_after_the_refresh_is_refused[None]"]},
    {"id": "A1-refresh-skipped", "file": SC,
     "old": "        refresh()\n        login = read_login()",
     "new": "        login = read_login()",
     "nodes": [f"{T_CRED}::test_a_short_login_is_refreshed_through_the_cli_then_reread"]},
    {"id": "A1-takes-the-refresh-token", "file": SC,
     "old": '    token = oauth.get("accessToken") if isinstance(oauth, dict) else None',
     "new": '    token = oauth.get("refreshToken") if isinstance(oauth, dict) else None',
     "nodes": [f"{T_CRED}::test_the_file_store_yields_only_the_access_token_and_expiry[linux]"]},
    {"id": "A1-keychain-suffix-dropped", "file": SC,
     "old": '    return f"{_KEYCHAIN_SERVICE}-{digest[:8]}"',
     "new": '    return _KEYCHAIN_SERVICE',
     "nodes": [f"{T_CRED}::test_a_custom_config_dir_suffixes_the_keychain_service"]},
    {"id": "A1-writable-store-accepted", "file": SC,
     "old": "                or stat.S_IMODE(info.st_mode) & 0o022\n",
     "new": "",
     "nodes": [f"{T_CRED}::test_an_unsuitable_file_store_is_no_login[group-writable]"]},
    {"id": "A1-expiry-not-classified", "file": PI,
     "old": "                if login and seat.expires_at is not None and time.time() >= seat.expires_at:",
     "new": "                if False:",
     "nodes": [f"{T_NOTE}::test_a_login_token_past_its_launch_expiry_is_its_own_relaunchable_outcome"]},
    {"id": "A1-login-limit-worded-as-override", "file": PI,
     "old": '                seat.notices.append("claude_seat_login_rate_limited" if login',
     "new": '                seat.notices.append("claude_seat_token_rate_limited" if login',
     "nodes": [f"{T_NOTE}::test_a_rate_limited_login_names_the_subscription"]},
    {"id": "A1-mode-skips-the-credential", "file": PI,
     "old": '            found = _claude_credential() if leg == "claude" else None',
     "new": '            found = None',
     "nodes": [f"{T_NOTE}::test_seat_modes_name_every_route_before_launch",
               f"{T_NOTE}::test_a_seat_that_will_be_refused_is_degraded_with_its_fix"]},
    {"id": "A1-cli-drops-seat-modes", "file": CL,
     "old": '            "seat_modes": [mode.as_json() for mode in seat_modes],',
     "new": '            "seat_modes": [],',
     "nodes": ["tests/test_seat_preflight_1204.py::test_cli_prints_every_seat_mode_and_carries_it_in_the_payload"]},
    # Plan amendment A2: the jail is qualified on first use.
    {"id": "A2-existing-pass-not-checked", "file": SA,
     "old": "    if verdict(digest)[0]:\n        return _remember(digest, Outcome(QUALIFIED))",
     "new": "    if False:\n        return _remember(digest, Outcome(QUALIFIED))",
     "nodes": [f"{T_AQ}::test_an_existing_pass_skips_the_qualification"]},
    {"id": "A2-no-host-lock", "file": SA,
     "old": "        fd = _acquire_lock(lock_wait_s)",
     "new": "        fd = os.open(os.devnull, os.O_RDONLY)",
     "nodes": [f"{T_AQ}::test_concurrent_first_use_runs_the_qualification_once"]},
    {"id": "A2-no-recheck-after-the-wait", "file": SA,
     "old": "        if verdict(digest)[0]:\n            return _remember(digest, Outcome(QUALIFIED_NOW))\n        cached",
     "new": "        if False:\n            return _remember(digest, Outcome(QUALIFIED_NOW))\n        cached",
     "nodes": [f"{T_AQ}::test_concurrent_first_use_runs_the_qualification_once"]},
    {"id": "A2-failure-not-cached", "file": SA,
     "old": "        _record_failure(digest, reason, now())",
     "new": "        pass",
     "nodes": [f"{T_AQ}::test_a_failure_is_typed_cached_and_not_retried_within_its_ttl"]},
    {"id": "A2-cache-ignores-the-layout", "file": SA,
     "old": "            or record.get(\"falsifier_layout\") != seat_jail.falsifier_layout_identity()\n",
     "new": "",
     "nodes": [f"{T_AQ}::test_a_cached_failure_is_retried_as_soon_as_the_digest_or_layout_changes[layout]"]},
    {"id": "A2-cache-never-expires", "file": SA,
     "old": "            or now - failed_at >= retry_after_s):",
     "new": "            ):",
     "nodes": [f"{T_AQ}::test_a_failure_is_typed_cached_and_not_retried_within_its_ttl"]},
    {"id": "A2-prerequisite-misclassified", "file": SA,
     "old": '            return "prerequisite_missing"',
     "new": '            return "error"',
     "nodes": [f"{T_AQ}::test_a_qualification_that_cannot_run_falls_back_with_a_typed_reason[exc0-prerequisite_missing]"]},
    {"id": "A2-mode-hides-qualified-now", "file": SRC / "seat_preflight.py",
     "old": '        mode = f"{self.mode} (qualified now)" if self.qualified_now else self.mode',
     "new": '        mode = self.mode',
     "nodes": [f"{T_NOTE}::test_a_jail_qualified_now_says_so_on_every_seat_of_the_board"]},
    {"id": "A2-mode-hides-the-reason", "file": PI,
     "old": '                                     f"{why}; reason: {reason}",',
     "new": '                                     why,',
     "nodes": [f"{T_NOTE}::test_a_failed_first_use_qualification_is_a_loud_sealed_mode"]},
    {"id": "A2-suite-guard-removed", "file": CONFTEST,
     "old": '    monkeypatch.setattr(seat_jail_autoqualify, "_default_qualify", _refuse)',
     "new": '    pass',
     "nodes": [f"{T_AQ}::test_the_suite_never_runs_a_real_first_use_qualification"]},
]


def _run(nodes: list[str]) -> dict[str, object]:
    # A fresh bytecode cache per run: a same-length mutation written in the same second
    # as the original keeps its (mtime, size) and CPython would reuse the stale .pyc,
    # running the UNMUTATED module and reporting a false "survived" (or a false control).
    import tempfile

    cache = tempfile.mkdtemp(prefix="seat-jail-mutation-pyc-")
    env = {**os.environ, "PYTHONPATH": str(RUNTIME / "src"), "PYTHONPYCACHEPREFIX": cache,
           "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "-o", "addopts=", *nodes], cwd=RUNTIME, env=env,
                              capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        # A mutation that makes the falsifier HANG (e.g. a blocking open on a FIFO) has not
        # passed it: record it as red, with the reason.
        return {"returncode": "timeout", "summary": "falsifier did not complete within 300 s"}
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
        ok = control["returncode"] == 0 and mutated["returncode"] not in (0,)
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
