"""Regression: cross-representation consistency of phase-plans-v10.md (agent-harness#375).

Guards against the defect class that shipped FOUR review rounds — a human-facing
representation (the ASCII DAG, the parallel-roots list, the serial-edges count, the
critical-path sentence, or the Execution-Notes root count) contradicting the structured
``**Depends on**`` field while ``roadmap_lint`` stayed green because it reads only the
structured field.

Two-arm, per verify-the-proof: the SHIPPED roadmap is clean AND an INJECTED
inconsistency of each representation is detected. A "today-clean" assertion over a
detector that cannot fire is vacuous, so every mutation first asserts it actually
changed the text (a no-op ``replace`` would otherwise pass silently).

Unmarked (no ``dotfiles_integration`` mark) so it gates in CI rather than skipping.
"""

from pathlib import Path

from phase_loop_runtime.roadmap_representation_check import (
    check_representation_consistency,
    check_roadmap,
)

# tests/ -> phase-loop-runtime/ -> repo root
V10 = Path(__file__).resolve().parents[2] / "specs" / "phase-plans-v10.md"


def _base() -> str:
    return V10.read_text(encoding="utf-8")


def _mutate(old: str, new: str) -> str:
    text = _base()
    mutated = text.replace(old, new)
    assert mutated != text, f"mutation anchor not found — test is stale for: {old!r}"
    return mutated


# --- ARM 1: the shipped roadmap agrees with itself ------------------------------------

def test_v10_representations_agree_with_structured_field():
    assert check_roadmap(V10) == []


# --- ARM 2: each representation's injected inconsistency is DETECTED -------------------

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


def test_detects_non_root_listed_as_parallel_root():
    # LEGLIFE **Depends on** REVIEWTRUTH — it is not a root.
    mutated = _mutate("∥ FABPUB ∥ HARDEN", "∥ FABPUB ∥ HARDEN ∥ LEGLIFE")
    findings = check_representation_consistency(mutated)
    assert any(f.representation == "parallel-roots" and "LEGLIFE" in f.message for f in findings), findings


def test_detects_wrong_execution_notes_root_count():
    mutated = _mutate(
        "Six phases are independent roots", "Seven phases are independent roots"
    )
    findings = check_representation_consistency(mutated)
    assert any(f.representation == "root-count" for f in findings), findings


def test_detects_serial_edge_count_mismatch():
    mutated = _mutate("Serial edges (four,", "Serial edges (three,")
    findings = check_representation_consistency(mutated)
    assert any(f.representation == "serial-edges" and "declares" in f.message for f in findings), findings


def test_detects_invented_ascii_dag_edge():
    # The bracket row for PROOFGATE draws it to SCHED; redirect it to an unbacked target.
    mutated = _mutate("┼─────────────→ SCHED", "┼─────────────→ LEGLIFE")
    findings = check_representation_consistency(mutated)
    assert any(
        f.representation == "ascii-dag" and "PROOFGATE → LEGLIFE" in f.message for f in findings
    ), findings
