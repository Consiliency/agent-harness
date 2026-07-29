"""Regression: cross-representation consistency of phase-plans-v10.md (agent-harness#375).

Guards against the defect class that shipped FOUR review rounds — a human-facing
representation (the ASCII DAG, the parallel-roots list, the serial-edges count, the
critical-path sentence, or the Execution-Notes root count) contradicting the structured
``**Depends on**`` field while ``roadmap_lint`` stayed green because it reads only the
structured field.

Two layers, per verify-the-proof:

  * PARSER-UNIT arms (ARM 0) exercise ``_bracket_edges`` directly with no file dependency,
    so they run EVERYWHERE — including Gate A's clean-room, which copies only ``tests/``
    (``gate_a_cleanroom.sh``) and does NOT ship ``specs/``. This keeps the clean-room run
    from hollowing out: even where the live doc is absent, the detector logic is exercised.
  * LIVE-DOC arms assert the SHIPPED roadmap is clean AND that an INJECTED inconsistency of
    each representation — every arrow shape the live DAG actually uses, continuation and
    join rows included — is detected. They ``skipif`` VISIBLY (reason shown under ``-rs``)
    when ``specs/`` is absent, and gate when present. Every mutation first asserts it
    actually changed the text (a no-op ``replace`` would otherwise pass silently).
"""

from pathlib import Path

import pytest

from phase_loop_runtime.roadmap_representation_check import (
    _bracket_edges,
    check_representation_consistency,
    check_roadmap,
)

# tests/ -> phase-loop-runtime/ -> repo root
V10 = Path(__file__).resolve().parents[2] / "specs" / "phase-plans-v10.md"

# The roadmap is not shipped into every tree (Gate A clean-room copies only tests/), so the
# live-doc arms must SKIP VISIBLY there while still gating in repo-rooted runs. A silent
# module-level skip would hollow the guard — the ARM-0 parser tests below carry no file
# dependency and run regardless, so coverage narrows without vacating (the hollow-guard
# defect agent-harness#382 spent three rounds killing).
_needs_v10 = pytest.mark.skipif(
    not V10.exists(),
    reason="specs/phase-plans-v10.md absent (e.g. Gate A clean-room copies only tests/); "
    "live-doc representation arms gate only in repo-rooted runs",
)


def _base() -> str:
    return V10.read_text(encoding="utf-8")


def _mutate(old: str, new: str) -> str:
    text = _base()
    mutated = text.replace(old, new)
    assert mutated != text, f"mutation anchor not found — test is stale for: {old!r}"
    return mutated


# --- ARM 0: parser primitives (NO file dependency — run in clean-room too) -------------

def test_bracket_edges_reads_same_line_and_continuation_arrows():
    # A source fans out across rows: FABREADMIT sits on FABPUB's own line; RESIDUAL sits on a
    # CONTINUATION row whose only alias is to the RIGHT of the arrow (its left operand is
    # FABPUB, inherited from above). Both must resolve to FABPUB — the shape `_edges_on_line`
    # alone was blind to. Pinned to the trace, not to "looks right".
    aliases = {"FABPUB", "FABREADMIT", "RESIDUAL", "HARDEN"}
    lines = [
        "FABPUB ───────────────┼──────┬──────→ FABREADMIT",
        "                      │      └──────→ RESIDUAL",
        "                      │",
        "HARDEN ───────────────┘",
    ]
    assert set(_bracket_edges(lines, aliases)) == {
        ("FABPUB", "FABREADMIT"),
        ("FABPUB", "RESIDUAL"),
    }


def test_bracket_edges_resets_source_on_blank_line():
    # A blank line ends a fan block: a bare continuation arrow after it has no source in
    # scope and must NOT inherit the previous block's alias. This bounds inheritance so a
    # later stray arrow can never be mis-attributed (the zero-FP guarantee).
    aliases = {"FABPUB", "FABREADMIT", "RESIDUAL"}
    lines = [
        "FABPUB ───────────────┬──────→ FABREADMIT",
        "",
        "          └──────→ RESIDUAL",  # orphaned: no source since the blank line
    ]
    edges = set(_bracket_edges(lines, aliases))
    assert edges == {("FABPUB", "FABREADMIT")}
    assert ("FABPUB", "RESIDUAL") not in edges  # orphan was NOT attributed to FABPUB


# --- ARM 1: the shipped roadmap agrees with itself ------------------------------------

@_needs_v10
def test_v10_representations_agree_with_structured_field():
    assert check_roadmap(V10) == []


# --- ARM 2: each representation's injected inconsistency is DETECTED -------------------

@_needs_v10
def test_detects_invented_critical_path_edge():
    # Reintroduce round-4's blocker: PROOFGATE -> FABPUB is not a structured edge, and the
    # single chain drops the co-equal PROOFGATE -> RUNTIME -> INTEG -> RELEASE path.
    mutated = _mutate(
        "Critical path (depth 4; two co-equal longest chains, both ending at the shared sink):\n"
        "  FABPUB    → FABREADMIT → INTEG → RELEASE\n"
        "  PROOFGATE → RUNTIME    → INTEG → RELEASE",
        "Critical path: PROOFGATE → FABPUB → FABREADMIT → INTEG → RELEASE",
    )
    findings = check_representation_consistency(mutated)
    assert any(
        f.representation == "critical-path" and "PROOFGATE → FABPUB" in f.message
        for f in findings
    ), findings


@_needs_v10
def test_detects_non_root_listed_as_parallel_root():
    # LEGLIFE **Depends on** REVIEWTRUTH — it is not a root.
    mutated = _mutate("∥ FABPUB ∥ HARDEN", "∥ FABPUB ∥ HARDEN ∥ LEGLIFE")
    findings = check_representation_consistency(mutated)
    assert any(f.representation == "parallel-roots" and "LEGLIFE" in f.message for f in findings), findings


@_needs_v10
def test_detects_wrong_execution_notes_root_count():
    # The Execution Notes now REFERENCE the fenced Parallel-roots list instead of restating a
    # count+list (agent-harness#375 dedup — a copy the checker cannot verify cannot drift).
    # This arm proves the root-count check still fires if a contradictory count sentence is
    # ever re-introduced into the notes: inject "Seven ... roots" while the field has 6.
    mutated = _mutate(
        "and execute them concurrently. RESIDUAL is not among them",
        "and execute them concurrently. Seven phases are independent roots. "
        "RESIDUAL is not among them",
    )
    findings = check_representation_consistency(mutated)
    assert any(f.representation == "root-count" for f in findings), findings


@_needs_v10
def test_detects_serial_edge_count_mismatch():
    mutated = _mutate("Serial edges (four,", "Serial edges (three,")
    findings = check_representation_consistency(mutated)
    assert any(f.representation == "serial-edges" and "declares" in f.message for f in findings), findings


@_needs_v10
def test_detects_invented_ascii_dag_edge():
    # Same-line bracket arrow: PROOFGATE draws to SCHED; redirect it to an unbacked target.
    mutated = _mutate("┼─────────────→ SCHED", "┼─────────────→ LEGLIFE")
    findings = check_representation_consistency(mutated)
    assert any(
        f.representation == "ascii-dag" and "PROOFGATE → LEGLIFE" in f.message for f in findings
    ), findings


@_needs_v10
def test_detects_invented_continuation_dag_edge():
    # CONTINUATION bracket arrow: the "└──────→ RESIDUAL" row under FABPUB's fan-out carries
    # no on-line left alias (source inherited). Corrupt the target to an unbacked alias — the
    # exact shape `_edges_on_line` was blind to. Source resolves to FABPUB.
    mutated = _mutate("└──────→ RESIDUAL", "└──────→ LEGLIFE")
    findings = check_representation_consistency(mutated)
    assert any(
        f.representation == "ascii-dag" and "FABPUB → LEGLIFE" in f.message for f in findings
    ), findings


@_needs_v10
def test_detects_invented_absorbed_join_edge():
    # JOIN arrow: the Absorbed chain's "FABPUB → FABREADMIT ─┴→ INTEG → RELEASE" row uses the
    # ─┴→ shape; corrupt its INTEG target to an unbacked alias.
    mutated = _mutate("─┴→ INTEG → RELEASE", "─┴→ LEGLIFE → RELEASE")
    findings = check_representation_consistency(mutated)
    assert any(
        f.representation == "absorbed-chain" and "→ LEGLIFE" in f.message for f in findings
    ), findings
