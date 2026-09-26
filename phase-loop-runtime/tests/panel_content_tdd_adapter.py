"""PANEL content-bound tests-first adapter (v10 Phase 18, agent-harness#1078).

A bounded wrapper over :mod:`phase_loop_runtime.tdd_receipts`, mirroring
``presroute_content_tdd_adapter.py``. SL-0 owns this file; SL-1, SL-2 and SL-3
consume its frozen bytes and never edit it. ``tdd_receipts.py`` is NOT edited.

What it provides
----------------
* **Readiness gating** for the three frozen PANEL test files
  (:func:`require_ready`). A node runs only once its slice's frozen symbol exists:

  - ``ec1_*``..``ec5_*`` and ``ec3e_*`` key on
    ``advisor_board.config.resolve_panel_table`` (slice 1);
  - ``ec6h_*`` keys on ``panel_invoker._seat_instructions`` AND
    ``panel_invoker.deliver_seat_prompt`` (slice 1's hook and delivery seam, landed together);
  - ``ec6_*`` and ``ec7_*`` key on ``advisor_board.lens_frame.render_lens_section``
    (slice 2).

  In an ordinary run a node whose key is absent SKIPS, so the corpus can land on
  ``main`` before SL-1/SL-2 without redding CI (the proofgate/PRESROUTE precedent).
  With ``PHASE_LOOP_TDD_EXPECT_PANEL=1`` NOTHING skips: an absent key FAILS with a
  RED anchor that names the node and the missing symbol. Only the key's OWN absence
  is treated as "not landed": a present module that fails to import for another
  reason (a broken dependency) propagates, and once the key exists every assertion
  in the node runs and a wrong implementation FAILS -- it is never skipped.

* **Activation semantics differ from PRESROUTE on purpose.** The plan defines
  ``PHASE_LOOP_TDD_EXPECT_PANEL=1`` as "disable every skip"; the acceptance commands
  and the phase suite run under it and must be GREEN after SL-1/SL-2. So a node
  that passes under activation is NOT an error here. The soundness of a RED
  recording therefore comes from :func:`scan_red_run`: at base EVERY collected node
  must FAIL, NONE may pass, skip, error or be deselected, and every failure must
  carry its OWN anchor (matched by exact node name) naming the readiness symbol of
  ITS group. A node that passes, fails for an unrelated reason (a typo, a
  ``NameError``) or anchors the wrong symbol makes ``record-red`` refuse.

* ``capture-golden``: the reproducible capture of
  ``tests/data/panel_code_review_snapshot.golden.json`` from the CURRENT code
  (``presets.CODE_REVIEW_BOARD``, ``resolver._STANDIN_CODE_REVIEW``,
  ``fixtures.DEFAULT_BOARD`` and every built-in preset task's seats). Each seat is
  the FULL ``Seat`` record (president follow-up F025) with only ``model`` replaced
  by its registry pin (``vendor/tier`` in ``profiles.TIER_MODELS``), so a registry
  model bump does not rebaseline the golden while any other seat drift does.
  ``capture-golden --check`` re-captures and compares bytes.

* ``record-red`` and ``verify`` (president follow-up F021). Both set
  ``PHASE_LOOP_TDD_EXPECT_PANEL=1`` themselves; neither trusts the caller's
  environment. The receipt binds this adapter's own bytes (it is a listed support
  file) and ``verify`` refuses a receipt that does not list it.

  - ``record-red`` records ``content_tdd_receipt.v1`` against the pre-implementation
    base and publishes it ONLY after :func:`scan_red_run` accepts the run.
  - ``verify --receipt-only`` checks the receipt (byte freeze, RED log digests,
    ancestry) and re-scans the recorded RED logs. It runs nothing. This is SL-0's
    own gate.
  - ``verify`` (bare, as the plan's ``suite_command`` calls it) does all of the
    above AND runs the three frozen files under activation, requiring every
    receipt-recorded node to PASS with zero skipped, failed, errored or deselected
    nodes. That GREEN half is SL-1/SL-2's to satisfy; it is red by construction
    on SL-0's own head.

* ``selfcheck``: a falsifier for the falsifier (no git state needed).

Freeze scope (deliberate, as PRESROUTE): the receipt freezes the BYTES of the files
it LISTS -- the three test files, this adapter and the golden -- not the file set.
A brand-new PANEL test file added after the freeze is the roadmap-ownership
workflow's and the touch-shape falsifier's concern, not this receipt's. Shared
test helpers the frozen tests import (``harden_tdd_guard.py``,
``president_fakes.py`` and the train fixtures) are NOT frozen here: SL-0 does not
own them and other phases import them.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

from phase_loop_runtime.tdd_receipts import (
    RED_ANCHOR_MARKER,
    record_content_tdd_receipt,
    verify_content_tdd_receipt,
)

PANEL_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_PANEL"

_TESTS_DIR = "phase-loop-runtime/tests"
FROZEN_TEST_FILES: tuple[str, ...] = (
    f"{_TESTS_DIR}/test_panel_lanes.py",
    f"{_TESTS_DIR}/test_panel_lens_delivery.py",
    f"{_TESTS_DIR}/test_panel_doc_contract.py",
)
ADAPTER_PATH = f"{_TESTS_DIR}/panel_content_tdd_adapter.py"
GOLDEN_PATH = f"{_TESTS_DIR}/data/panel_code_review_snapshot.golden.json"
FROZEN_SUPPORT_FILES: tuple[str, ...] = (ADAPTER_PATH, GOLDEN_PATH)
RECEIPT_PATH = ".phase-loop/evidence/PANEL/content-tdd-receipt.json"

# ``--tb=short`` keeps every per-node FAILED summary line and each node's anchor
# (the AssertionError message) while printing no traceback locals: no process
# addresses and no per-user pytest temp paths reach this permanent artefact. The
# short traceback renders repository frames relative to the invocation root (the
# repository root, where ``record-red`` runs). ``-p no:cacheprovider`` keeps a
# ``.pytest_cache`` out of the run. As for PRESROUTE, the RED log is the record of
# ONE run that ``verify`` re-hashes and re-scans; it never re-runs pytest to compare.
# The anchor prefix is :data:`RED_ANCHOR_MARKER`, owned by the shared
# ``content_tdd_receipt.v1`` mechanism (it reads "GOVLEAN ..."); the phase-specific
# marker is ``PANEL_RED::``.
RED_COMMAND = "python3 -m pytest -q --tb=short --color=no -p no:cacheprovider " + " ".join(FROZEN_TEST_FILES)
GREEN_ARGV: tuple[str, ...] = (
    sys.executable, "-m", "pytest", "-q", "--tb=short", "--color=no", "-p", "no:cacheprovider", "-rA",
    *FROZEN_TEST_FILES,
)

# Drift guard beside the receipt's own collected node list: the number of nodes
# each frozen file collects at freeze time.
EXPECTED_NODE_COUNTS: dict[str, int] = {
    "test_panel_lanes": 335,
    "test_panel_lens_delivery": 19,
    "test_panel_doc_contract": 12,
}


class ReadinessKey(NamedTuple):
    module: str
    attr: str  # one attribute, or several joined by "+" (all must exist)
    slice_label: str

    @property
    def symbol(self) -> str:
        return f"{self.module}.{self.attr}"

    @property
    def attrs(self) -> tuple[str, ...]:
        return tuple(self.attr.split("+"))


SLICE1 = ReadinessKey("phase_loop_runtime.advisor_board.config", "resolve_panel_table", "slice 1")
HOOK = ReadinessKey(
    "phase_loop_runtime.panel_invoker", "_seat_instructions+deliver_seat_prompt", "slice 1 lens hook and delivery seam"
)
SLICE2 = ReadinessKey("phase_loop_runtime.advisor_board.lens_frame", "render_lens_section", "slice 2")
READINESS_KEYS: tuple[ReadinessKey, ...] = (SLICE1, HOOK, SLICE2)


def key_for_node(name: str) -> ReadinessKey:
    """The readiness key a node's group is bound to, derived from its name.

    Order matters: ``test_ec6h_`` must be matched before ``test_ec6_``.
    """
    if name.startswith("test_ec6h_"):
        return HOOK
    if name.startswith(("test_ec6_", "test_ec7_")):
        return SLICE2
    if re.match(r"test_ec(1|2|3|3e|4|5)_", name):
        return SLICE1
    raise AssertionError(f"PANEL node {name!r} belongs to no readiness group")


def panel_active() -> bool:
    return os.environ.get(PANEL_ACTIVATION_ENV) == "1"


def _current_node() -> tuple[str, str]:
    """``(file stem, node name)`` of the running test, from ``PYTEST_CURRENT_TEST``."""
    current = os.environ.get("PYTEST_CURRENT_TEST", "")
    nodeid = current.rsplit(" (", 1)[0]
    path, _, rest = nodeid.partition("::")
    return Path(path).stem, rest.split("::")[-1]


def panel_red_message(stem: str, name: str, key: ReadinessKey) -> str:
    return f"{RED_ANCHOR_MARKER} PANEL_RED::{stem}::{name} missing={key.symbol}"


def _symbol_present(key: ReadinessKey):
    """Return the module when ``key`` is present, ``None`` when ONLY it is absent."""
    try:
        module = importlib.import_module(key.module)
    except ModuleNotFoundError as exc:
        if exc.name == key.module:
            return None
        raise  # a present module with a broken dependency is not "not landed"
    return module if all(hasattr(module, attr) for attr in key.attrs) else None


def require_ready(key: ReadinessKey):
    """Gate the running node on its readiness key; return the key's module.

    Absent key: FAIL with the node's RED anchor under activation, SKIP otherwise.
    The key must be the one :func:`key_for_node` assigns to the running node, so a
    node cannot silently key on a different slice than its group.
    """
    stem, name = _current_node()
    expected = key_for_node(name)
    if expected != key:
        raise AssertionError(
            f"PANEL node {name} gates on {key.symbol} but its group keys on {expected.symbol}"
        )
    module = _symbol_present(key)
    if module is not None:
        return module
    if panel_active():
        raise AssertionError(panel_red_message(stem, name, key))
    import pytest

    pytest.skip(f"PANEL {key.slice_label} not landed: {key.symbol} is absent")


# --- golden capture ---------------------------------------------------------------


def model_pin(model: str) -> str:
    """The registry pin of a concrete model id: ``<vendor>/<tier>`` in ``TIER_MODELS``.

    Refuses an id no registry cell carries, so an unpinned seat cannot be captured.
    """
    from phase_loop_runtime.profiles import TIER_MODELS

    for vendor, cells in TIER_MODELS.items():
        for tier, cell in cells.items():
            if cell.model_id == model:
                return f"{vendor}/{tier}"
    raise ValueError(f"model {model!r} is not a registry pin in profiles.TIER_MODELS")


def seat_record(seat) -> dict:
    """The full ``Seat`` record with only ``model`` normalized to its registry pin (F025)."""
    record = dataclasses.asdict(seat)
    record["model_pin"] = model_pin(record.pop("model"))
    return dict(sorted(record.items()))


def board_record(board) -> dict:
    return {
        "name": board.name,
        "purpose": board.purpose,
        "allow_api_key_fallback": board.allow_api_key_fallback,
        "research_enabled": board.research_policy.enabled,
        "seats": [seat_record(seat) for seat in board.seats],
    }


def capture_golden() -> dict:
    from phase_loop_runtime.advisor_board import resolver
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from phase_loop_runtime.advisor_board.presets import CODE_REVIEW_BOARD, PRESETS

    return {
        "schema": "panel_code_review_snapshot.v1",
        "model_normalization": "profiles.TIER_MODELS <vendor>/<tier>",
        "import_time": {
            "presets.CODE_REVIEW_BOARD": board_record(CODE_REVIEW_BOARD),
            "resolver._STANDIN_CODE_REVIEW": board_record(resolver._STANDIN_CODE_REVIEW),
            "fixtures.DEFAULT_BOARD": board_record(DEFAULT_BOARD),
        },
        "preset_tasks": {name: board_record(board) for name, board in sorted(PRESETS.items())},
    }


def golden_bytes() -> bytes:
    return (json.dumps(capture_golden(), indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_golden(repo: Path | None = None) -> dict:
    root = repo if repo is not None else Path(__file__).resolve().parents[2]
    return json.loads((root / GOLDEN_PATH).read_text(encoding="utf-8"))


# --- RED-run soundness --------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_ANCHOR_RE = re.compile(r"PANEL_RED::([A-Za-z0-9_]+)::(\S+?) missing=(\S+)")
_FAILED_RE = re.compile(r"(?m)^FAILED\s+(\S+)")


def _node_key(nodeid: str) -> tuple[str, str]:
    path, _, rest = nodeid.partition("::")
    return Path(path).stem, rest.split("::")[-1]


def _summary_count(category: str, output: str) -> int:
    match = re.search(rf"(\d+) {category}s?\b", output)
    return int(match.group(1)) if match else 0


def scan_red_run(output: str, collected: Iterable[str]) -> str | None:
    """Return an error unless ``output`` is sound RED evidence for ``collected``.

    Sound means: every collected node FAILED and nothing else happened (no pass,
    skip, error, deselect, xfail/xpass); every failed node carries its OWN anchor,
    matched exactly by file stem and node name; each anchor names the readiness
    symbol of its node's group; the per-file node counts equal the frozen counts.
    """
    output = _ANSI_RE.sub("", output)  # a forced-colour environment must not hide a node
    nodes = {_node_key(nodeid) for nodeid in collected}
    if not nodes:
        return "no collected nodes"
    counts: dict[str, int] = {}
    for stem, _name in nodes:
        counts[stem] = counts.get(stem, 0) + 1
    if counts != EXPECTED_NODE_COUNTS:
        return f"collected node counts {counts} != frozen {EXPECTED_NODE_COUNTS}"
    if RED_ANCHOR_MARKER not in output:
        return "RED anchor marker missing from output"
    failed = {_node_key(nodeid) for nodeid in _FAILED_RE.findall(output)}
    if failed != nodes:
        return (
            f"failed set != collected set (missing {sorted(nodes - failed)[:5]}, "
            f"extra {sorted(failed - nodes)[:5]})"
        )
    if _summary_count("failed", output) != len(nodes):
        return f"expected {len(nodes)} failed, saw {_summary_count('failed', output)}"
    for category in ("passed", "skipped", "deselected", "error", "xfailed", "xpassed"):
        count = _summary_count(category, output)
        if count:
            return f"RED run has {count} {category} node(s); every node must be red-for-reason"
    anchored: dict[tuple[str, str], str] = {}
    for stem, name, symbol in _ANCHOR_RE.findall(output):
        anchored[(stem, name)] = symbol
    unanchored = sorted(nodes - set(anchored))
    if unanchored:
        return f"failed nodes without their own RED anchor (unrelated failure?): {unanchored[:5]}"
    stray = sorted(set(anchored) - nodes)
    if stray:
        return f"RED anchors for uncollected nodes: {stray[:5]}"
    for (stem, name), symbol in sorted(anchored.items()):
        expected = key_for_node(name.split("[", 1)[0])
        if symbol != expected.symbol:
            return f"{stem}::{name} anchors {symbol}, but its group keys on {expected.symbol}"
    return None


_PASSED_RE = re.compile(r"(?m)^PASSED\s+(\S+)")


def scan_green_run(output: str, returncode: int, expected_nodeids: Iterable[str]) -> str | None:
    """GREEN at head: exit 0, and the EXACT receipt-recorded node set passed (``-rA``
    lists every PASSED node) -- not merely the same count -- with nothing else.

    Ids are compared by ``(file stem, node name)``, as the RED anchors are: the receipt
    records ROOTDIR-relative ids (``tests/test_panel_lanes.py::…``, from ``--collect-only``)
    while ``-rA`` prints CWD-relative ids (``phase-loop-runtime/tests/test_panel_lanes.py::…``
    when run from the repository root). The three frozen stems are distinct."""
    output = _ANSI_RE.sub("", output)
    if returncode != 0:
        return f"GREEN run exited {returncode}"
    expected = {_node_key(nodeid) for nodeid in expected_nodeids}
    passed_ids = {_node_key(nodeid) for nodeid in _PASSED_RE.findall(output)}
    if passed_ids != expected:
        return (
            f"passed node set != recorded set (missing {sorted(expected - passed_ids)[:5]}, "
            f"extra {sorted(passed_ids - expected)[:5]})"
        )
    passed = _summary_count("passed", output)
    if passed != len(expected):
        return f"expected {len(expected)} passed, saw {passed}"
    for category in ("failed", "skipped", "deselected", "error", "xfailed", "xpassed"):
        count = _summary_count(category, output)
        if count:
            return f"GREEN run has {count} {category} node(s); zero skips at head is required"
    return None


# --- record / verify ------------------------------------------------------------------


def _default_repo() -> Path:
    return Path(__file__).resolve().parents[2]


def _activated_env(repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    env[PANEL_ACTIVATION_ENV] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            f"{repo}/phase-loop-runtime/src",
            f"{repo}/phase-loop-runtime/tests",
            os.environ.get("PYTHONPATH"),
        )
        if part
    )
    return env


def _record_red(repo: Path, landing_ref: str, receipt_path: Path) -> int:
    prior = {key: os.environ.get(key) for key in (PANEL_ACTIVATION_ENV, "PYTHONPATH")}
    os.environ.update({key: _activated_env(repo)[key] for key in prior})
    staging = Path(tempfile.mkdtemp(prefix="panel-record-red-"))
    staged_receipt = staging / receipt_path.name
    try:
        receipt = record_content_tdd_receipt(
            repo=repo,
            test_glob=FROZEN_TEST_FILES[0],
            red_command=RED_COMMAND,
            landing_ref=landing_ref,
            out=staged_receipt,
            support_paths=(*FROZEN_TEST_FILES[1:], *FROZEN_SUPPORT_FILES),
        )
        red_output = (staging / receipt.red_stdout_path).read_text(encoding="utf-8") + (
            staging / receipt.red_stderr_path
        ).read_text(encoding="utf-8")
        error = scan_red_run(red_output, receipt.red_nodeids)
        if error:
            print(f"panel record-red: {error} (no receipt published)", file=sys.stderr)
            return 1
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        for name in (receipt_path.name, receipt.red_stdout_path, receipt.red_stderr_path):
            shutil.copyfile(staging / name, receipt_path.parent / name)
    except Exception as exc:  # noqa: BLE001 - surface the recorder's typed error
        print(f"panel record-red failed: {exc} (no receipt published)", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print(
        f"panel record-red: recorded RED receipt at {receipt_path} "
        f"({len(receipt.red_nodeids)} nodes red for their readiness symbol)"
    )
    return 0


def _bind_requested_landing(repo: Path, payload: dict, landing_ref: str) -> str | None:
    for item in payload.get("test_files", ()):
        rel = item.get("path", "")
        shown = subprocess.run(["git", "show", f"{landing_ref}:{rel}"], cwd=repo, capture_output=True)
        if shown.returncode:
            return f"requested landing {landing_ref!r} does not contain frozen file {rel}"
        if hashlib.sha256(shown.stdout).hexdigest() != item.get("sha256"):
            return f"requested landing {landing_ref!r} carries a changed frozen file {rel}"
    return None


def _verify(repo: Path, receipt_path: Path, landing_ref: str | None, receipt_only: bool) -> int:
    os.environ[PANEL_ACTIVATION_ENV] = "1"  # F021: never trust the caller's environment
    try:
        result = verify_content_tdd_receipt(receipt_path=receipt_path, repo=repo)
    except Exception as exc:  # noqa: BLE001 - surface the recorder's typed error
        print(f"panel verify failed: {exc}", file=sys.stderr)
        return 2
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    bound = {item.get("path") for item in payload.get("test_files", ())}
    missing = sorted(set(FROZEN_TEST_FILES + FROZEN_SUPPORT_FILES) - bound)
    if missing:
        print(f"panel verify failed: receipt does not bind {missing}", file=sys.stderr)
        return 2
    red_output = (receipt_path.parent / result.red_stdout_path).read_text(encoding="utf-8") + (
        receipt_path.parent / result.red_stderr_path
    ).read_text(encoding="utf-8")
    error = scan_red_run(red_output, result.red_nodeids)
    if error:
        print(f"panel verify failed: recorded RED evidence is unsound: {error}", file=sys.stderr)
        return 2
    if landing_ref:
        error = _bind_requested_landing(repo, payload, landing_ref)
        if error:
            print(f"panel verify failed: {error}", file=sys.stderr)
            return 2
    if not receipt_only:
        green = subprocess.run(
            list(GREEN_ARGV), cwd=repo, capture_output=True, text=True, env=_activated_env(repo)
        )
        error = scan_green_run(green.stdout + green.stderr, green.returncode, result.red_nodeids)
        if error:
            print(green.stdout[-4000:], file=sys.stderr)
            print(f"panel verify failed: frozen corpus is not GREEN at head: {error}", file=sys.stderr)
            return 1
    scope = "receipt-only" if receipt_only else "receipt + GREEN at head, zero skips"
    print(f"panel verify: ok ({scope}) landing_commit={result.landing_commit}")
    return 0


# --- selfcheck ------------------------------------------------------------------------


def _selfcheck() -> int:
    failures: list[str] = []
    stems = list(EXPECTED_NODE_COUNTS)
    names = {
        "test_panel_lanes": ["test_ec1_a", "test_ec3e_b[runner]", "test_ec6h_c"],
        "test_panel_lens_delivery": ["test_ec6_d"],
        "test_panel_doc_contract": ["test_ec7_e"],
    }
    counts = {stem: len(names[stem]) for stem in stems}
    collected = [f"tests/{stem}.py::{name}" for stem in stems for name in names[stem]]

    def anchor(stem: str, name: str, key: ReadinessKey | None = None) -> str:
        key = key or key_for_node(name.split("[", 1)[0])
        return f"E   AssertionError: {panel_red_message(stem, name, key)}"

    def run(lines: list[str], summary: str) -> str:
        return "\n".join(lines + [summary])

    canonical = [f"FAILED {nodeid} - AssertionError" for nodeid in collected] + [
        anchor(stem, name) for stem in stems for name in names[stem]
    ]
    total = len(collected)
    saved = dict(EXPECTED_NODE_COUNTS)
    EXPECTED_NODE_COUNTS.clear()
    EXPECTED_NODE_COUNTS.update(counts)
    try:
        if scan_red_run(run(canonical, f"{total} failed in 1.0s"), collected) is not None:
            failures.append("canonical RED run rejected")
        green_one = [line for line in canonical if "test_ec7_e" not in line]
        if scan_red_run(run(green_one, f"{total - 1} failed, 1 passed in 1.0s"), collected) is None:
            failures.append("a node that PASSED under activation was accepted as RED")
        unrelated = [line for line in canonical if "PANEL_RED::test_panel_lanes::test_ec1_a " not in line]
        unrelated.append("E   NameError: name 'typo' is not defined")
        if scan_red_run(run(unrelated, f"{total} failed in 1.0s"), collected) is None:
            failures.append("an unanchored (unrelated) failure was accepted as RED")
        wrong_key = [
            line if "::test_ec6_d " not in line else anchor("test_panel_lens_delivery", "test_ec6_d", SLICE1)
            for line in canonical
        ]
        if scan_red_run(run(wrong_key, f"{total} failed in 1.0s"), collected) is None:
            failures.append("an anchor naming the wrong readiness symbol was accepted")
        skipped = [line for line in canonical if "test_ec6h_c" not in line]
        if scan_red_run(run(skipped, f"{total - 1} failed, 1 skipped in 1.0s"), collected) is None:
            failures.append("a skipped node was accepted as RED")
        if scan_red_run(run(canonical, f"{total} failed in 1.0s"), collected[:-1]) is None:
            failures.append("a changed collected set was accepted")
        green_lines = "\n".join(f"PASSED {nodeid}" for nodeid in collected)
        if scan_green_run(f"{green_lines}\n{total} passed in 1.0s", 0, collected) is not None:
            failures.append("a clean GREEN run was rejected")
        # The REAL shapes: the receipt holds rootdir-relative ids (``tests/…``) while ``-rA``
        # run from the repository root prints ``phase-loop-runtime/tests/…``.
        realistic = "\n".join(f"PASSED phase-loop-runtime/{nodeid}" for nodeid in collected)
        if scan_green_run(f"{realistic}\n{total} passed in 1.0s", 0, collected) is not None:
            failures.append("a real-shaped GREEN run (cwd-relative -rA ids vs rootdir-relative receipt ids) was rejected")
        renamed = realistic.replace("test_ec7_e", "test_ec7_renamed")
        if scan_green_run(f"{renamed}\n{total} passed in 1.0s", 0, collected) is None:
            failures.append("a GREEN run with the same count but a different node set was accepted")
        if scan_green_run(f"{green_lines}\n{total - 1} passed, 1 skipped in 1.0s", 0, collected) is None:
            failures.append("a GREEN run with a skip was accepted")
    finally:
        EXPECTED_NODE_COUNTS.clear()
        EXPECTED_NODE_COUNTS.update(saved)

    try:
        key_for_node("test_unkeyed_node")
    except AssertionError:
        pass
    else:
        failures.append("an unkeyed node name was assigned a readiness group")
    if key_for_node("test_ec6h_x") is not HOOK or key_for_node("test_ec6_x") is not SLICE2:
        failures.append("ec6h/ec6 prefixes resolve to the wrong readiness key")

    absent = ReadinessKey("phase_loop_runtime._panel_selfcheck_absent_xyz", "x", "selfcheck")
    if _symbol_present(absent) is not None:
        failures.append("an absent module was reported present")
    scratch = Path(tempfile.mkdtemp(prefix="panel-selfcheck-"))
    (scratch / "_panel_selfcheck_brokendep.py").write_text(
        "import a_dependency_module_that_does_not_exist_xyz\n", encoding="utf-8"
    )
    sys.path.insert(0, str(scratch))
    try:
        _symbol_present(ReadinessKey("_panel_selfcheck_brokendep", "x", "selfcheck"))
    except ModuleNotFoundError:
        pass
    else:
        failures.append("a broken dependency was laundered into 'not landed'")
    finally:
        sys.path.remove(str(scratch))
        sys.modules.pop("_panel_selfcheck_brokendep", None)
        shutil.rmtree(scratch, ignore_errors=True)

    if golden_bytes() != golden_bytes():
        failures.append("golden capture is not reproducible in-process")

    if failures:
        for line in failures:
            print(f"panel selfcheck FAILED: {line}", file=sys.stderr)
        return 1
    print(
        "panel selfcheck: recording path sound (passing node, unrelated failure, wrong symbol, "
        "skip and set drift all refused; broken dependency propagates; golden reproducible)"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PANEL content TDD adapter")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selfcheck")
    cap = sub.add_parser("capture-golden")
    cap.add_argument("--out", type=Path, default=None)
    cap.add_argument("--check", action="store_true")
    rec = sub.add_parser("record-red")
    rec.add_argument("--repo", type=Path, default=None)
    rec.add_argument("--landing-ref", default="HEAD")
    rec.add_argument("--receipt", type=Path, default=None)
    ver = sub.add_parser("verify")
    ver.add_argument("--repo", type=Path, default=None)
    ver.add_argument("--receipt", type=Path, default=None)
    ver.add_argument("--landing-ref", default=None)
    ver.add_argument(
        "--receipt-only", action="store_true",
        help="check the receipt and re-scan its RED logs; do not require GREEN at head (SL-0's gate)",
    )
    args = parser.parse_args(argv)

    if args.command == "selfcheck":
        return _selfcheck()
    if args.command == "capture-golden":
        data = golden_bytes()
        target = args.out or (_default_repo() / GOLDEN_PATH)
        if args.check:
            if not target.is_file() or target.read_bytes() != data:
                print(f"panel capture-golden: {target} differs from a fresh capture", file=sys.stderr)
                return 1
            print(f"panel capture-golden: {target} reproduces byte-for-byte")
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"panel capture-golden: wrote {target} sha256={hashlib.sha256(data).hexdigest()}")
        return 0
    repo = (args.repo or _default_repo()).resolve()
    receipt_path = (args.receipt or (repo / RECEIPT_PATH)).resolve()
    if args.command == "record-red":
        return _record_red(repo, args.landing_ref, receipt_path)
    return _verify(repo, receipt_path, args.landing_ref, args.receipt_only)


if __name__ == "__main__":
    raise SystemExit(main())
