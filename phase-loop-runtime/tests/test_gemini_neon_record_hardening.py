"""agy qualification records that launched Gemini 4 NEON pass the validator's argv predicate.

Registering NEON widens what ``validate_records`` admits: it hardens each recorded argv model
through ``backing.harden_subscription_model("gemini", argv[2], None)``, so a record whose argv
names ``gemini-4-neon-medium`` or ``-high`` was refused before NEON was registered and now
passes. The fixed corpus (``fixtures/agy_validator_corpus``) cannot show this, because it only
carries Argon records plus an unknown ``gemini-other`` and a foreign OpenAI model. These tests
copy each corpus record in memory, swap the argv model and re-derive the fields bound to the
argv (the broker's argv shape and its digest, and the record digests). The corpus files and
the pinned verdict vector are not touched (``test_agy_qci.py``).

``-xhigh`` stays refused (Gemini effort is capped at ``high``), and an unregistered
``gemini-4-other-medium`` is refused exactly like the corpus's ``gemini-other`` case.
"""

from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from phase_loop_runtime import agy_qualification as q

CORPUS = Path(__file__).resolve().parent / "fixtures" / "agy_validator_corpus"
OPERATIONS = ("completion", "cancel", "owner-loss")
ARGON_MEDIUM = "gemini-4-argon-medium"  # model-id-source: the corpus records' argv model


def _expected() -> dict:
    return json.loads((CORPUS / "expected.json").read_text())


def _corpus_record(operation: str) -> dict:
    return json.loads((CORPUS / "series" / operation / "qualification.json").read_text())


def _with_argv_model(operation: str, model: str) -> dict:
    record = copy.deepcopy(_corpus_record(operation))
    assert record["observer"]["argv"][2] == ARGON_MEDIUM
    record["observer"]["argv"][2] = model
    broker = record.get("broker")
    if broker is not None:
        shape = list(record["observer"]["argv"]) + ["<STDIN_SEALED_INLINE_PROMPT>"]
        broker["provider_argv_shape"] = shape
        broker["provider_argv_sha256"] = sha256("\0".join(shape).encode()).hexdigest()
        broker["provider_model"] = model
    record["record_sha256"] = {
        name: q.digest(record[name]) for name in ("monitoring", "broker", "observer", "result") if name in record
    }
    return record


@pytest.mark.parametrize("operation", OPERATIONS)
def test_the_unmodified_corpus_record_still_passes(operation):
    # Control: the re-derivation above is a no-op for the recorded Argon model.
    q.validate_records(_with_argv_model(operation, ARGON_MEDIUM), **_expected())


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("model", ["gemini-4-neon-medium", "gemini-4-neon-high"])  # model-id-source: admitted NEON argv
def test_a_neon_record_passes_the_argv_predicate(operation, model):
    q.validate_records(_with_argv_model(operation, model), **_expected())


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("model", ["gemini-4-neon-xhigh", "gemini-4-other-medium", "gemini-4-neon"])
def test_an_inadmissible_neon_argv_is_refused(operation, model):
    # Hardening raises ValueError for an unrenderable or unregistered model, which is the
    # same outcome the corpus pins for ``shared_argv`` (``raise:ValueError``). A bare base id
    # is refused by the argv render check: the recorded argv must carry the rendered effort.
    with pytest.raises((ValueError, q.QualificationFailure)):
        q.validate_records(_with_argv_model(operation, model), **_expected())


def test_the_fixed_corpus_still_names_only_argon():
    # The corpus is historical evidence; NEON coverage lives here, not in the fixture.
    text = "".join(path.read_text() for path in sorted((CORPUS / "series").rglob("*.json")))
    assert "gemini-4-neon" not in text
