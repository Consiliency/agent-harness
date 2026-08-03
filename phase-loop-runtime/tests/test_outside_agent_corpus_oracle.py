"""Assert the canonical corpus's declared *reason*, not just its pass/block bit.

`test_outside_agent_canonical_corpus.py` drives every vector through OUR validator
and checks `expected_valid` — the pass/block outcome. But the manifest also declares,
per vector, an `expected_verdict` (roadmap_intake / review_candidate /
needs_clarification / reject) and an `expected_blocker_class`
(none / missing_information / unsafe_evidence_reference / policy_gap). Nothing
asserted those, so a vector could carry a wrong declared reason silently — the same
self-authored-fixture blind spot that hid agent-harness#371 for four rounds, one
layer down: right pass/block bit, wrong *why*.

Our conformance gate deliberately does NOT compute that routing taxonomy — it emits
a coarser `schema_validation_failed` code, and re-deriving spec's classification here
would be the exact hand-mirroring that caused #371. So the reason is asserted with
spec's OWN normative oracle, `outside_agent_router.route()`, vendored byte-identically
from the same v0.2.1 commit as the corpus (provenance + digest in `_contract/VENDOR.json`,
enforced by the drift guard in the canonical-corpus test).

SCOPE, stated precisely: this is a DRIFT GUARD on the vendored corpus — it proves each
vector's declared verdict/class is what spec's logic actually derives from the vendored
payload+schema. It is NOT a test of our validator's reasoning (agent-harness has no
router component to test); our validator's coarser blocker taxonomy is a known dialect
boundary reported in the PR, not something this file closes. Only `route` and
`blocker_class_of` are used — never `blocker.summary`, which by contract carries no
submitted content but is also not part of the corpus's declared vocabulary.
"""
from __future__ import annotations

import json
import types
from importlib import resources
from pathlib import Path

import pytest
from jsonschema.validators import Draft202012Validator

CONTRACT_ROOT = Path(str(resources.files("phase_loop_runtime.conformance") / "_contract"))
MANIFEST_PATH = CONTRACT_ROOT / "test-vectors" / "outside-agent" / "manifest.json"
ORACLE_PATH = CONTRACT_ROOT / "oracle" / "outside_agent_router.py"
VERDICT_SCHEMA_PATH = CONTRACT_ROOT / "schemas" / "outside-agent-route-verdict.schema.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_oracle() -> types.ModuleType:
    """Load the vendored spec oracle hermetically from its file path.

    Compiled-and-exec'd by path (not imported as an installed package) so the
    test binds to the digest-pinned vendored copy, never an ambient
    ``consiliency_spec`` install. ``__file__`` is set so the module's
    ``_schema_dir()`` resolves to ``<file>.parent.parent/"schemas"`` =
    ``_contract/schemas`` — it validates against the SAME vendored schemas, and
    its lazy ``from . import load_json`` fallback is only reached when that dir is
    absent, which it is not.

    A manual ``exec(compile(...))`` is used deliberately in place of
    ``importlib`` machinery: the latter writes ``__pycache__/*.pyc`` next to the
    source on first import, and because ``_contract/**`` is a package-data glob,
    that bytecode would be non-deterministically swept into the wheel depending
    on whether tests ran before the build. Manual exec writes no bytecode, so the
    vendored oracle ships as exactly one file.
    """
    module = types.ModuleType("vendored_oa_router")
    module.__file__ = str(ORACLE_PATH)
    source = ORACLE_PATH.read_text(encoding="utf-8")
    exec(compile(source, str(ORACLE_PATH), "exec"), module.__dict__)  # noqa: S102
    return module


ORACLE = _load_oracle()
VERDICT_VALIDATOR = Draft202012Validator(_load_json(VERDICT_SCHEMA_PATH))


def _manifest_entries() -> list[dict]:
    manifest = _load_json(MANIFEST_PATH)
    assert manifest["manifest_schema_version"] == "outside_agent_vector_manifest.v0.1"
    entries = manifest["vectors"]
    assert entries, "canonical manifest must not be empty"
    return entries


_ENTRIES = _manifest_entries()


def _oracle_derived_class(entry: dict) -> str:
    """The blocker class the oracle actually derives from a vector's payload."""
    payload = _load_json(CONTRACT_ROOT / entry["path"])
    return ORACLE.blocker_class_of(ORACLE.route(payload, entry["schema_target"]))


def _assert_declared_class_matches_oracle(entry: dict) -> None:
    """The guard's core equality, factored so a falsifier can drive the SAME check.

    Both the parametrized guard and the declared-class-drift falsifier below call
    this, so ``pytest.raises(AssertionError)`` there proves the guard catches a
    tampered declaration — not merely that some other assertion is false.
    """
    derived = _oracle_derived_class(entry)
    assert derived == entry["expected_blocker_class"], (
        f"{entry['case_id']}: oracle derived blocker class {derived!r} "
        f"!= manifest expected_blocker_class {entry['expected_blocker_class']!r}"
    )


@pytest.mark.parametrize("entry", _ENTRIES, ids=[e["case_id"] for e in _ENTRIES])
def test_oracle_derives_each_vector_declared_verdict_and_blocker_class(entry: dict) -> None:
    """Every vector's declared verdict AND blocker class must be what the oracle derives."""
    payload = _load_json(CONTRACT_ROOT / entry["path"])
    verdict = ORACLE.route(payload, entry["schema_target"])

    assert verdict["route"] == entry["expected_verdict"], (
        f"{entry['case_id']}: oracle derived route {verdict['route']!r} "
        f"!= manifest expected_verdict {entry['expected_verdict']!r}"
    )
    _assert_declared_class_matches_oracle(entry)
    assert not list(VERDICT_VALIDATOR.iter_errors(verdict)), (
        f"{entry['case_id']}: oracle-derived verdict is not route-verdict-schema-valid"
    )


def test_guard_catches_a_wrong_declared_class_in_the_manifest() -> None:
    """Condition-2 primary arm: a manifest that declares the WRONG class fails closed.

    The guard's stated primary threat is a corpus silently carrying a wrong declared
    class. Take a real negative vector, flip its ``expected_blocker_class`` to a value
    the oracle does NOT derive from the (byte-for-byte unchanged) payload, and assert
    the guard's own equality — ``_assert_declared_class_matches_oracle`` — goes RED.
    This exercises the declared-class-drift arm the review named; the payload-drift
    arm is covered by the sibling test below.
    """
    negative = next(e for e in _ENTRIES if not e["expected_valid"])

    # Positive control: the real entry passes the guard's own check.
    _assert_declared_class_matches_oracle(negative)

    # Falsifier: same payload, a tampered declared class -> the guard's check fails.
    wrong_class = next(
        candidate
        for candidate in ("missing_information", "unsafe_evidence_reference", "policy_gap")
        if candidate != negative["expected_blocker_class"]
    )
    tampered = {**negative, "expected_blocker_class": wrong_class}
    with pytest.raises(AssertionError):
        _assert_declared_class_matches_oracle(tampered)


def test_guard_is_falsifiable_a_mismatched_payload_would_fail() -> None:
    """Non-vacuity, payload-drift arm: prove the equality FIRES when the payload moves.

    Positive control (guard passes when consistent): a positive vector's declared
    ``none`` IS what the oracle derives from its unmutated payload. Falsifier (guard
    would go RED): mutating that payload so the oracle derives a DIFFERENT class,
    while the manifest still declares ``none``, makes the per-vector assertion above
    false. Without this, a corpus whose payloads never matched their declared classes
    could pass the parametrized check vacuously (vacuity form: assertion reads an
    observable that never moves).
    """
    positive = next(e for e in _ENTRIES if e["expected_valid"])
    assert positive["expected_blocker_class"] == "none"
    payload = _load_json(CONTRACT_ROOT / positive["path"])

    # Positive control: consistent corpus passes.
    clean_verdict = ORACLE.route(payload, positive["schema_target"])
    assert clean_verdict["route"] == positive["expected_verdict"]
    assert ORACLE.blocker_class_of(clean_verdict) == positive["expected_blocker_class"]

    # Falsifier: shift the derived class; the declared class ("none") no longer matches.
    corrupted = json.loads(json.dumps(payload))
    corrupted["evidence_refs"] = []
    corrupted_verdict = ORACLE.route(corrupted, positive["schema_target"])
    assert corrupted_verdict["route"] == "reject"
    derived_class = ORACLE.blocker_class_of(corrupted_verdict)
    assert derived_class == "missing_information"  # the oracle DID move
    assert derived_class != positive["expected_blocker_class"], (
        "guard is vacuous: a payload that should reject still derives the declared class"
    )


def test_every_negative_vector_declares_a_distinguishing_blocker_class() -> None:
    """The corpus must actually EXERCISE the class distinction, not just carry it.

    If every negative declared the same class, the parametrized assertion would be
    green while proving nothing about class fidelity. Assert the negatives span more
    than one non-``none`` class (the manifest spreads them across
    unsafe_evidence_reference / missing_information / policy_gap).
    """
    negative_classes = {
        e["expected_blocker_class"] for e in _ENTRIES if not e["expected_valid"]
    }
    assert "none" not in negative_classes
    assert len(negative_classes) >= 2, (
        f"negatives collapse to a single class {negative_classes!r} — the class "
        f"assertion would not distinguish reasons"
    )
