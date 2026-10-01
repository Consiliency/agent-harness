"""Named mutations for agent-harness#1204: each must turn its named node(s) red."""
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
RT = Path(__file__).resolve().parents[3] / "phase-loop-runtime"
SRC = RT / "src/phase_loop_runtime"
T = "tests/test_seat_preflight_1204.py"
M = [
 ("P1-preflight-never-runs", SRC/"panel_invoker.py", "        if pointer_brief:\n            # The PRODUCTION route", "        if False:\n            # The PRODUCTION route",
  [f"{T}::test_chunker114_shape_the_preflight_warns_before_any_launch_and_the_seats_still_run"]),
 ("P2-not-published-before-launch", SRC/"panel_invoker.py", "            if on_seat_preflight is not None:\n                on_seat_preflight(seat_preflight_notices)\n", "",
  [f"{T}::test_chunker114_shape_the_preflight_warns_before_any_launch_and_the_seats_still_run"]),
 ("P3-seats-never-marked", SRC/"panel_invoker.py", "        attach_seat_preflight_notices(results, seat_preflight_notices)\n", "",
  [f"{T}::test_chunker114_shape_the_preflight_warns_before_any_launch_and_the_seats_still_run"]),
 ("P4-route-capability-ignored", SRC/"seat_preflight.py", "    return staged_tree and bool(sandbox_usable_by(leg, brokered=brokered))", "    return staged_tree",
  [f"{T}::test_brokered_seats_without_file_tools_are_warned_on_a_staged_tree"]),
 ("P5-native-fill-ignored", SRC/"seat_preflight.py", "    if native_fill:\n        return True\n", "",
  [f"{T}::test_a_native_fill_claude_seat_has_file_access"]),
 ("P6-staged-tree-ignored", SRC/"seat_preflight.py", "    return staged_tree and bool(sandbox_usable_by", "    return True and bool(sandbox_usable_by",
  [f"{T}::test_without_a_staged_tree_no_brokered_seat_can_open_the_files"]),
 ("C1-governed-counts-ungrounded", SRC/"governed_review.py", "    if not any(counts_as_grounded_vote(leg, counts_toward_landing) for leg in panel.legs):", "    if not any(counts_toward_landing(leg) for leg in panel.legs):",
  [f"{T}::test_governed_landing_needs_a_grounded_seat"]),
 ("C2-governed-notice-finding-dropped", SRC/"governed_review.py", "        for notice in leg_notices(leg):\n", "        for notice in ():\n",
  [f"{T}::test_governed_notice_finding_is_rendered_from_literals_and_warns"]),
 ("C3-president-counts-ungrounded", SRC/"panel_invoker.py", "        elif (ungrounded := _seat_preflight.uncounted_president_items(\n                leg, terminal_verdict)) is not None:", "        elif False and (ungrounded := _seat_preflight.uncounted_president_items(\n                leg, terminal_verdict)) is not None:",
  [f"{T}::test_president_input_does_not_count_an_ungrounded_pass_but_keeps_its_disagree"]),
 ("C4-ungrounded-disagree-dropped", SRC/"seat_preflight.py", "    if terminal_verdict(getattr(leg, \"text\", \"\")) == \"DISAGREE\":\n        return None\n", "",
  [f"{T}::test_president_input_does_not_count_an_ungrounded_pass_but_keeps_its_disagree"]),
 ("C5-cli-floor-counts-ungrounded", SRC/"cli.py", "    usable = grounded_count >= FLOOR_SEATS", "    usable = usable_count >= FLOOR_SEATS",
  [f"{T}::test_cli_pointer_brief_prints_preflight_and_floors_on_grounded_seats"]),
 ("C6-premerge-floor-counts-ungrounded", SRC/"governed_premerge.py", "        if gate.panel is not None and len(grounded_usable_legs(gate.panel)) < _MIN_USABLE_REVIEWERS:", "        if gate.panel is not None and len(gate.panel.usable_legs) < _MIN_USABLE_REVIEWERS:",
  [f"{T}::test_premerge_reviewer_floor_does_not_count_an_ungrounded_seat"]),
 ("C7-cli-flag-not-forwarded", SRC/"cli.py", "                invoke_kwargs[\"pointer_brief\"] = True\n", "",
  [f"{T}::test_cli_pointer_brief_prints_preflight_and_floors_on_grounded_seats"]),
 ("C8-payload-changed-without-flag", SRC/"cli.py", "        if pointer_brief:\n            # agent-harness#1204: present only", "        if True:\n            # agent-harness#1204: present only",
  [f"{T}::test_cli_without_pointer_brief_keeps_the_payload_unchanged"]),
 ("C9-stream-record-not-atomic", SRC/"seat_preflight.py", "    tmp.replace(path)\n", "    tmp.replace(path)\n    tmp.write_text('x')\n",
  [f"{T}::test_the_stream_record_is_published_atomically"]),
]
def run(nodes):
    env = {**os.environ, "PYTHONPATH": str(RT/"src"), "PYTHONPYCACHEPREFIX": tempfile.mkdtemp(), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("CLAUDECODE", None); env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    try:
        d = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", *nodes], cwd=RT, env=env, capture_output=True, text=True, timeout=300)
        return d.returncode
    except subprocess.TimeoutExpired:
        return "timeout"
out, bad = [], []
for mid, path, old, new, nodes in M:
    orig = path.read_bytes(); text = orig.decode()
    assert text.count(old) == 1, (mid, text.count(old))
    control = run(nodes)
    try:
        path.write_text(text.replace(old, new, 1)); mutated = run(nodes)
    finally:
        path.write_bytes(orig)
    ok = control == 0 and mutated != 0
    if not ok: bad.append(mid)
    out.append({"id": mid, "file": str(path.relative_to(RT)), "file_sha256": hashlib.sha256(orig).hexdigest(), "nodes": nodes, "control": control, "mutated": mutated, "result": "red_as_required" if ok else "survived"})
    print(mid, out[-1]["result"], flush=True)
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RT, capture_output=True, text=True).stdout.strip()
(Path(__file__).resolve().parent / "mutation-receipts.json").write_text(json.dumps({"issue": "agent-harness#1204", "head": head, "receipts": out, "survived": bad}, indent=2) + "\n")
print("SURVIVED", bad)
