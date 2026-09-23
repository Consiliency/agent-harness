"""PRESROUTE content-bound tests-first adapter (v10 Phase 14, agent-harness#952).

A bounded wrapper over :mod:`phase_loop_runtime.tdd_receipts` (mirroring
``proofgate_content_tdd_adapter.py``). SL-0 owns this file; SL-1 and SL-2 consume
its frozen bytes and never edit it.

It provides:

* the RED-anchor contract wrapper the two frozen PRESROUTE test files call
  (:func:`run_presroute_contract`), plus the capability probes those contracts
  use (:func:`require_module`, :func:`require_attr`, :func:`require_capability`).
  A contract signals "the pre-implementation capability is absent" ONLY by
  raising :class:`PresrouteMissingCapabilityError`; that is the sole thing the
  wrapper maps onto the recorded RED marker. Any OTHER exception (a collection
  error, a genuine contract violation) propagates unchanged, and an UNEXPECTED
  SUCCESS is a hard error — so ``record-red`` can never certify an already-green
  implementation or a broken test as RED.
* the ``record-red`` and ``verify`` subcommands. ``record-red`` requires every
  declared falsifier to fire (matched exactly, not by substring) and rejects any
  ``PRESROUTE_RECORD_UNSOUND`` sentinel. ``verify`` checks the source receipt
  (``content_tdd_receipt.v1``) AND, when given ``--landing-ref``, separately binds
  that requested landing to the receipt's frozen manifest byte-equal.
  ``tdd_receipts.py`` is NOT edited.

Freeze scope (deliberate): ``content_tdd_receipt.v1`` freezes the BYTES of the
files it LISTS (the two pinned tests, this adapter, and the golden fixture), not
the file SET. Adding a brand-new PRESROUTE falsifier file AFTER the freeze is
out of scope for the receipt and is NOT caught by ``verify``; it is caught by the
roadmap-ownership workflow and the phase's touch-shape falsifier, which gate WHICH
paths a landing PR may touch (SL-0 is the single writer of these files). The
receipt guarantees the listed bytes never drift; the file set is an
ownership-review guarantee.

Run ``selfcheck`` to prove the recording path itself is sound (an already-green
contract and an unrelated error must both be rejected, markers matched exactly)
without needing any git state.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from phase_loop_runtime.tdd_receipts import (
    RED_ANCHOR_MARKER,
    record_content_tdd_receipt,
    verify_content_tdd_receipt,
)

# The receipt mechanism keys its own subprocess activation on
# ``PHASE_LOOP_TDD_EXPECT_GOVLEAN`` and requires ``RED_ANCHOR_MARKER`` in the RED
# output. The PRESROUTE frozen tests key their deliberate anchor on this distinct
# env var, which ``_record_red`` sets in ``os.environ`` so it is inherited into
# the pytest subprocess the receipt recorder spawns.
PRESROUTE_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_PRESROUTE"

# Sentinel emitted when a contract unexpectedly PASSES under activation: an
# already-green base must never be recorded as RED. It deliberately does NOT
# contain a ``PRESROUTE_RED::`` marker, and ``record-red`` fails on sight of it.
RECORD_UNSOUND_SENTINEL = "PRESROUTE_RECORD_UNSOUND"

# Case ids the two frozen test files emit through :func:`run_presroute_contract`.
# ``record-red`` asserts every one appears EXACTLY (not by substring) in the
# recorded RED output, so a silently-dropped falsifier cannot be recorded as RED.
EXPECTED_RED_CASES: tuple[str, ...] = (
    # test_president_wiring.py
    "operation",
    "authorization",
    "review_authorization_refused",
    "launch_provider",
    "native_fable",
    "heartbeat",
    "brief_binding",
    "ruling_record",
    "findings_digest",
    "ruling_record_matches_frozen_contract",
    "route_failure",
    # test_govlean_panel_policy.py
    "ladder",
    "requires_president_false_refused",
)

# The exact per-node outcome a sound RED run must show: these thirteen pinned nodes
# fail (each for its stated reason -- see the marker check), the twenty-seven other
# nodes pass, and NOTHING else is red, skipped, deselected, errored, or missing. A
# marker set proves what fired, never what else happened or what never ran.
EXPECTED_RED_NODES: tuple[str, ...] = (
    "test_president_operation_routes_seated_rung_through_public_board_president",
    "test_president_authorization_identity_minted_like_review_isolation",
    "test_president_operation_refuses_a_review_authorization",
    "test_non_native_rung_launches_only_through_launch_provider",
    "test_native_fable_rung_filled_under_claude_code_without_second_tui",
    "test_native_president_fill_refused_under_heartbeat_only",
    "test_brief_binding_rejects_changed_brief_at_resume_and_accepts_control",
    "test_ruling_record_written_to_review_stream_with_identity",
    "test_findings_digest_recomputes_from_prompt_findings",
    "test_ruling_record_matches_frozen_contract",
    "test_adapter_route_failure_is_not_a_ladder_descent",
    "test_president_ladder_is_the_ec_presroute_3_seat_alias_order",
    "test_plan_or_production_requires_president_false_refused",
)
EXPECTED_PASS_COUNT = 27

_TESTS_DIR = "phase-loop-runtime/tests"
FROZEN_TEST_FILES: tuple[str, ...] = (
    f"{_TESTS_DIR}/test_president_wiring.py",
    f"{_TESTS_DIR}/test_govlean_panel_policy.py",
)
FROZEN_SUPPORT_FILES: tuple[str, ...] = (
    f"{_TESTS_DIR}/presroute_content_tdd_adapter.py",
    f"{_TESTS_DIR}/data/president_ruling_v1.golden.json",
    # The shared test helpers the two pinned tests import -- ``president_fakes.py``,
    # ``harden_tdd_guard.py``, ``govlean_freeze_receipt.py`` -- are deliberately NOT
    # frozen here. None is owned by SL-0 (they are absent from PRESROUTE's owned-files
    # and single-writer sets in the plan), and each is imported by other phases' test
    # modules -- ``president_fakes.py`` alone is imported by six test modules including
    # REVIEWTRUTH's ``test_native_claude_seat_fill.py`` -- so freezing its bytes here
    # would couple this receipt to a concurrent phase's edits and break merge-time
    # ``verify`` on an additive change SL-0 does not control. Fixture drift in a
    # non-owned shared helper is the roadmap-ownership workflow's concern, not this
    # receipt's.
)
RECEIPT_PATH = ".phase-loop/evidence/PRESROUTE/content-tdd-receipt.json"
# ``--tb=short`` keeps the per-node ``FAILED`` summary lines, the summary counts,
# and each contract's ``PRESROUTE_RED::<case>`` anchor (which lives in the
# AssertionError message) while printing NO traceback locals. So the two
# machine-specific residues a fuller traceback would embed in this PERMANENT frozen
# artifact never appear: process memory addresses (``<function ... at 0x...>``) and
# per-user pytest temp paths (``/tmp/pytest-of-<user>/...``). The short traceback
# renders the test and adapter frames relative to the invocation root -- the
# repository root, from which ``record-red`` runs -- so the absolute checkout path a
# bare ``__file__`` carries never reaches the log. The ONE absolute path that
# remains is the standard-library ``importlib`` frame of a ``ModuleNotFoundError``
# (``/usr/lib/pythonX.Y/importlib/__init__.py``): a fixed system path with no
# checkout layout, username, or temp directory in it. This is the first committed
# ``content_tdd_receipt.v1`` artifact in the repo, so it sets precedent.
# ``-p no:cacheprovider`` keeps a ``.pytest_cache`` out of the run.
#
# REPRODUCIBILITY (deliberate): even so, the RED log is NOT a reproducible artifact
# -- run durations and any incidental ordering vary between runs. It is the record
# of ONE recorded RED run against the frozen bytes. ``verify`` RE-HASHES the stored
# log bytes; it never re-runs pytest to compare. So a downstream golden digest of
# this log (e.g. EXECFIND's) attests to that one recorded run, not to an artifact
# that can be regenerated and diffed.
#
# ONE RESIDUE, documented rather than removed: each anchor reads
# ``GOVLEAN deliberate RED anchor PRESROUTE_RED::<case>``. The prefix is
# :data:`RED_ANCHOR_MARKER`, owned by the shared content_tdd_receipt.v1 mechanism
# (``phase_loop_runtime.tdd_receipts``, which SL-0 MUST NOT edit). It is the
# MECHANISM's marker, not a claim that this evidence belongs to GOVLEAN; the
# phase-specific marker is ``PRESROUTE_RED::<case>``.
RED_COMMAND = "python3 -m pytest -q --tb=short -p no:cacheprovider " + " ".join(FROZEN_TEST_FILES)

_MARKER_RE = re.compile(r"PRESROUTE_RED::([A-Za-z0-9_]+)")


class PresrouteMissingCapabilityError(AssertionError):
    """Raised by a frozen contract when the capability it exercises is absent.

    :func:`run_presroute_contract` handles it in BOTH modes: under ``record-red``
    it is the ONLY signal converted into the recorded RED anchor; in an ordinary
    (non-activated) run it is caught and the node is SKIPPED, so a corpus that
    lands before SL-1/SL-2 keeps ordinary CI green while the capability is
    unimplemented. The frozen receipt -- recorded under activation -- not an
    ordinary run, is the loud RED proof. Any OTHER exception from a contract (a
    genuine violation once implemented) is never a missing capability and
    propagates, so a wrong implementation still FAILS, never skips.
    """


def require_module(modname: str):
    """Import ``modname``; treat ONLY its own absence as a missing capability.

    A ``ModuleNotFoundError`` naming a DIFFERENT module (a broken dependency
    inside a present implementation) or any other ``ImportError`` propagates
    unchanged, so a broken import is never laundered into "the feature is absent".
    """
    try:
        return importlib.import_module(modname)
    except ModuleNotFoundError as exc:
        if exc.name == modname:
            raise PresrouteMissingCapabilityError(f"module {modname!r} absent") from exc
        raise


def require_attr(obj, name: str):
    if not hasattr(obj, name):
        raise PresrouteMissingCapabilityError(
            f"{getattr(obj, '__name__', obj)!r} has no attribute {name!r}"
        )
    return getattr(obj, name)


def require_capability(condition: object, detail: str) -> None:
    if not condition:
        raise PresrouteMissingCapabilityError(detail)


def presroute_active() -> bool:
    """True during ``record-red``: the deliberate RED anchor must fire."""
    return os.environ.get(PRESROUTE_ACTIVATION_ENV) == "1"


def presroute_red_message(case_id: str) -> str:
    return f"{RED_ANCHOR_MARKER} PRESROUTE_RED::{case_id}"


def run_presroute_contract(case_id: str, contract_fn: Callable[[], None]) -> None:
    """Run one post-implementation contract.

    * Under activation (``record-red``): a contract that raises
      :class:`PresrouteMissingCapabilityError` records the RED anchor; a contract
      that PASSES is a hard error (an already-green base must not be recorded as
      RED); any other exception propagates unchanged (a collection error or a
      genuine contract violation is not evidence of a missing feature).
    * Otherwise (an ordinary run, e.g. CI): a missing capability SKIPS the node,
      mirroring the proofgate precedent, so the corpus is green-with-skips on the
      pre-implementation base rather than red -- a corpus landing before SL-1/SL-2
      must not red the shared pipeline for the whole time it is unimplemented --
      and each node passes once SL-1/SL-2 land. Any OTHER exception propagates, so
      a wrong implementation FAILS. Redness is proven by the frozen receipt under
      activation, never by an ordinary run.
    """
    if presroute_active():
        try:
            contract_fn()
        except PresrouteMissingCapabilityError as exc:
            raise AssertionError(presroute_red_message(case_id)) from exc
        raise AssertionError(
            f"{RECORD_UNSOUND_SENTINEL}::{case_id}: the contract passed on the "
            "pre-implementation base; refusing to record it as RED"
        )
    try:
        contract_fn()
    except PresrouteMissingCapabilityError as exc:
        import pytest

        pytest.skip(f"presroute capability unimplemented for {case_id}: {exc}")


def _repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(proc.stdout.strip()).resolve()


def _record_red(repo: Path, landing_ref: str, receipt_path: Path) -> int:
    import shutil
    import tempfile

    prior_activation = os.environ.get(PRESROUTE_ACTIVATION_ENV)
    prior_pythonpath = os.environ.get("PYTHONPATH")
    os.environ[PRESROUTE_ACTIVATION_ENV] = "1"
    os.environ["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            f"{repo}/phase-loop-runtime/src",
            f"{repo}/phase-loop-runtime/tests",
            prior_pythonpath,
        )
        if part
    )
    # Record into a staging directory FIRST; publish to the final path only after
    # the scan accepts, so a rejected recording never leaves a usable receipt.
    staging = Path(tempfile.mkdtemp(prefix="presroute-record-red-"))
    staged_receipt = staging / receipt_path.name
    try:
        receipt = record_content_tdd_receipt(
            repo=repo,
            test_glob=FROZEN_TEST_FILES[0],
            red_command=RED_COMMAND,
            landing_ref=landing_ref,
            out=staged_receipt,
            support_paths=(FROZEN_TEST_FILES[1], *FROZEN_SUPPORT_FILES),
        )
        red_output = (
            (staging / receipt.red_stdout_path).read_text(encoding="utf-8")
            + (staging / receipt.red_stderr_path).read_text(encoding="utf-8")
        )
        error = scan_red_output(red_output) or scan_pytest_outcomes(red_output)
        if error:
            print(f"presroute record-red: {error} (no receipt published)", file=sys.stderr)
            return 1
        # Accepted: publish atomically-ish, replacing any prior artefacts.
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        for name in (
            receipt_path.name,
            receipt.red_stdout_path,
            receipt.red_stderr_path,
        ):
            shutil.copyfile(staging / name, receipt_path.parent / name)
    except Exception as exc:  # noqa: BLE001 - surface the recorder's typed error
        print(f"presroute record-red failed: {exc} (no receipt published)", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if prior_activation is None:
            os.environ.pop(PRESROUTE_ACTIVATION_ENV, None)
        else:
            os.environ[PRESROUTE_ACTIVATION_ENV] = prior_activation
        if prior_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = prior_pythonpath
    print(
        "presroute record-red: recorded RED receipt at "
        f"{receipt_path} (exit 1, {len(EXPECTED_RED_CASES)} falsifiers fired exactly)"
    )
    return 0


def scan_red_output(red_output: str) -> str | None:
    """Return an error string if the RED output is not sound evidence, else None.

    Rejects: an unexpected-success sentinel (an already-green contract), a missing
    RED anchor, any declared falsifier that never fired (matched EXACTLY, not by
    substring, so one case id cannot stand in for another), and any stray marker.
    """
    if RECORD_UNSOUND_SENTINEL in red_output:
        return (
            f"an already-green contract was seen ({RECORD_UNSOUND_SENTINEL}); refusing to record"
        )
    if RED_ANCHOR_MARKER not in red_output:
        return "RED anchor marker missing from output"
    fired = set(_MARKER_RE.findall(red_output))
    missing = [case_id for case_id in EXPECTED_RED_CASES if case_id not in fired]
    if missing:
        return f"RED cases never fired: {missing}"
    unexpected = sorted(fired - set(EXPECTED_RED_CASES))
    if unexpected:
        return f"unexpected RED markers: {unexpected}"
    return None


def _summary_count(category: str, output: str) -> int:
    match = re.search(rf"(\d+) {category}s?\b", output)
    return int(match.group(1)) if match else 0


def scan_pytest_outcomes(output: str) -> str | None:
    """Return an error unless the run shows the EXACT expected per-node outcomes.

    The thirteen pinned nodes must be the ONLY failures, the twenty-seven other
    nodes must pass, and nothing may be skipped, deselected, errored, or lost -- so
    a node that also went red (while the thirteen still fired their markers) is
    caught here, not accepted because the exit code was 1 either way.
    """
    failed = set(re.findall(r"(?m)^FAILED\s+\S+::([A-Za-z0-9_]+)", output))
    expected = set(EXPECTED_RED_NODES)
    extra = sorted(failed - expected)
    if extra:
        return f"unexpected failing nodes: {extra}"
    missing = sorted(expected - failed)
    if missing:
        return f"expected-red nodes did not fail: {missing}"
    failed_count = _summary_count("failed", output)
    if failed_count != len(EXPECTED_RED_NODES):
        return f"expected {len(EXPECTED_RED_NODES)} failed, saw {failed_count}"
    passed_count = _summary_count("passed", output)
    if passed_count != EXPECTED_PASS_COUNT:
        return f"expected {EXPECTED_PASS_COUNT} passed, saw {passed_count}"
    for category in ("skipped", "deselected", "error", "xfailed", "xpassed"):
        count = _summary_count(category, output)
        if count:
            return f"run has {count} {category} node(s); every node must be red-for-reason or green"
    return None


def _bind_requested_landing(repo: Path, receipt_path: Path, landing_ref: str) -> str | None:
    """Return an error string if ``landing_ref`` does not carry the frozen manifest
    byte-equal to the receipt, else ``None``.

    The source receipt proves provenance of the frozen bytes; this separately
    binds the REQUESTED landing, so pointing ``--landing-ref`` at a commit whose
    tests were altered fails instead of being silently ignored.
    """
    import json

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    for item in payload.get("test_files", ()):
        rel = item.get("path", "")
        completed = subprocess.run(
            ["git", "show", f"{landing_ref}:{rel}"], cwd=repo, capture_output=True
        )
        if completed.returncode:
            return f"requested landing {landing_ref!r} does not contain frozen file {rel}"
        if hashlib.sha256(completed.stdout).hexdigest() != item.get("sha256"):
            return f"requested landing {landing_ref!r} carries a changed frozen file {rel}"
    return None


def _verify(repo: Path, receipt_path: Path, landing_ref: str | None) -> int:
    try:
        result = verify_content_tdd_receipt(receipt_path=receipt_path, repo=repo)
    except Exception as exc:  # noqa: BLE001 - surface the recorder's typed error
        print(f"presroute verify failed: {exc}", file=sys.stderr)
        return 2
    # Re-validate the recorded RED logs themselves rather than trusting that
    # recording refused: a receipt whose logs are not sound RED evidence (an
    # already-green sentinel, a missing or stray marker) must not verify.
    red_output = (
        (receipt_path.parent / result.red_stdout_path).read_text(encoding="utf-8")
        + (receipt_path.parent / result.red_stderr_path).read_text(encoding="utf-8")
    )
    error = scan_red_output(red_output) or scan_pytest_outcomes(red_output)
    if error:
        print(f"presroute verify failed: recorded RED evidence is unsound: {error}", file=sys.stderr)
        return 2
    if landing_ref:
        error = _bind_requested_landing(repo, receipt_path, landing_ref)
        if error:
            print(f"presroute verify failed: {error}", file=sys.stderr)
            return 2
    suffix = f" landing_ref={landing_ref}" if landing_ref else ""
    print(f"presroute verify: ok landing_commit={result.landing_commit}{suffix}")
    return 0


def _selfcheck() -> int:
    """A falsifier for the falsifier: prove the recording path is sound.

    Exercises :func:`run_presroute_contract` and :func:`scan_red_output` directly
    (no git state), asserting an already-green contract and an unrelated error are
    both rejected and markers are matched exactly.
    """
    prior = os.environ.get(PRESROUTE_ACTIVATION_ENV)
    os.environ[PRESROUTE_ACTIVATION_ENV] = "1"
    failures: list[str] = []
    try:
        # 1. a missing capability records the anchor.
        try:
            run_presroute_contract(
                "operation",
                lambda: (_ for _ in ()).throw(PresrouteMissingCapabilityError("absent")),
            )
        except AssertionError as exc:
            if RED_ANCHOR_MARKER not in str(exc) or "PRESROUTE_RED::operation" not in str(exc):
                failures.append("missing-capability did not record the RED anchor")
        else:
            failures.append("missing-capability did not fail")

        # 2. an already-green contract is rejected as unsound (no anchor).
        try:
            run_presroute_contract("operation", lambda: None)
        except AssertionError as exc:
            if RECORD_UNSOUND_SENTINEL not in str(exc) or RED_ANCHOR_MARKER in str(exc):
                failures.append("green contract was not rejected as unsound")
        else:
            failures.append("green contract did not fail")

        # 3. an unrelated error propagates raw (never becomes a RED marker).
        try:
            run_presroute_contract(
                "operation", lambda: (_ for _ in ()).throw(RuntimeError("unrelated"))
            )
        except RuntimeError:
            pass
        except AssertionError:
            failures.append("unrelated error was laundered into an assertion/marker")
        else:
            failures.append("unrelated error did not propagate")
    finally:
        if prior is None:
            os.environ.pop(PRESROUTE_ACTIVATION_ENV, None)
        else:
            os.environ[PRESROUTE_ACTIVATION_ENV] = prior

    # 4. scan rejects a green run, a missing case, and an exact-substring collision.
    all_fired = "\n".join(presroute_red_message(c) for c in EXPECTED_RED_CASES)
    if scan_red_output(all_fired) is not None:
        failures.append("scan rejected a fully-fired RED run")
    if scan_red_output(all_fired + f"\n{RECORD_UNSOUND_SENTINEL}::operation") is None:
        failures.append("scan accepted an unsound (green) run")
    substring_only = "\n".join(
        presroute_red_message(c) for c in EXPECTED_RED_CASES if c != "ruling_record"
    )
    verdict = scan_red_output(substring_only)
    if verdict is None or "ruling_record" not in verdict:
        failures.append("scan let a longer case id satisfy 'ruling_record' by substring")

    # 5. a rejected recording leaves nothing to publish: an unsound run's output
    #    is rejected by the scan that gates the write, so no receipt is produced.
    if scan_red_output(all_fired + f"\n{RECORD_UNSOUND_SENTINEL}::ladder") is None:
        failures.append("scan accepted a run whose contract passed (would publish an unsound receipt)")

    # 6. require_module treats ONLY the requested module's own absence as a missing
    #    capability; a broken dependency inside a PRESENT module propagates.
    import sys as _sys
    import tempfile as _tempfile

    if require_module("os") is not _sys.modules["os"]:
        failures.append("require_module did not return a present module")
    try:
        require_module("phase_loop_runtime._presroute_selfcheck_absent_xyz")
    except PresrouteMissingCapabilityError:
        pass
    except Exception:  # noqa: BLE001
        failures.append("require_module did not report an absent module as a missing capability")
    else:
        failures.append("require_module did not fail on an absent module")

    _pkg = Path(_tempfile.mkdtemp(prefix="presroute-selfcheck-"))
    (_pkg / "_presroute_selfcheck_brokendep.py").write_text(
        "import a_dependency_module_that_does_not_exist_xyz\n", encoding="utf-8"
    )
    _sys.path.insert(0, str(_pkg))
    try:
        require_module("_presroute_selfcheck_brokendep")
    except PresrouteMissingCapabilityError:
        failures.append("require_module laundered a broken dependency into a missing capability")
    except ModuleNotFoundError:
        pass  # the real dependency error propagated, as required
    except Exception:  # noqa: BLE001
        pass
    else:
        failures.append("require_module did not surface a broken dependency import")
    finally:
        _sys.path.remove(str(_pkg))
        import shutil as _shutil

        _shutil.rmtree(_pkg, ignore_errors=True)
        _sys.modules.pop("_presroute_selfcheck_brokendep", None)

    # 7. scan_pytest_outcomes requires the EXACT per-node outcome, so an invariant
    #    that also went red (while all thirteen anchors fired) is caught -- a marker
    #    set proves what fired, never what else failed.
    canonical = (
        "\n".join(f"FAILED phase-loop-runtime/tests/x.py::{n}" for n in EXPECTED_RED_NODES)
        + f"\n{len(EXPECTED_RED_NODES)} failed, {EXPECTED_PASS_COUNT} passed in 1.00s\n"
    )
    if scan_pytest_outcomes(canonical) is not None:
        failures.append("scan_pytest_outcomes rejected the canonical per-node outcome")
    extra_red = (
        canonical.replace(
            f"{len(EXPECTED_RED_NODES)} failed, {EXPECTED_PASS_COUNT} passed",
            f"{len(EXPECTED_RED_NODES) + 1} failed, {EXPECTED_PASS_COUNT - 1} passed",
        )
        + "FAILED phase-loop-runtime/tests/x.py::test_an_invariant_also_broke\n"
    )
    if scan_pytest_outcomes(extra_red) is None:
        failures.append("scan_pytest_outcomes accepted a run with an extra failing invariant")
    skipped_run = canonical.replace(
        f"{EXPECTED_PASS_COUNT} passed", f"{EXPECTED_PASS_COUNT - 1} passed, 1 skipped"
    )
    if scan_pytest_outcomes(skipped_run) is None:
        failures.append("scan_pytest_outcomes accepted a run with a skipped node")

    if failures:
        for line in failures:
            print(f"presroute selfcheck FAILED: {line}", file=sys.stderr)
        return 1
    print(
        "presroute selfcheck: recording path sound (green + unrelated-error + "
        "exact-marker + unpublished-on-reject + require_module + per-node-outcome)"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRESROUTE content TDD adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("selfcheck")

    rec = subparsers.add_parser("record-red")
    rec.add_argument("--repo", type=Path, default=None)
    rec.add_argument("--landing-ref", default="HEAD")
    rec.add_argument("--receipt", type=Path, default=None)

    ver = subparsers.add_parser("verify")
    ver.add_argument("--repo", type=Path, required=True)
    # When supplied, the requested landing is bound to the receipt's frozen
    # manifest (byte-equal) in addition to the receipt's own provenance checks.
    ver.add_argument("--landing-ref", default=None)
    ver.add_argument("--receipt", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "selfcheck":
        return _selfcheck()
    repo = (args.repo or _repo_root()).resolve()

    if args.command == "record-red":
        receipt_path = (args.receipt or (repo / RECEIPT_PATH)).resolve()
        return _record_red(repo, args.landing_ref, receipt_path)
    if args.command == "verify":
        return _verify(repo, args.receipt.resolve(), args.landing_ref)
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
