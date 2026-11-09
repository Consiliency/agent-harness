"""The seat QCI and the semantic validator guard (AGYROLL §2.1; RECBIND SL-1, EC-RECBIND-2).

``seat_qci()`` equals ``agy_profile_digest()`` at ``agy_validator_v1``. What "passed" means is
guarded two ways:

- the **semantic guard** (primary): a fixed corpus (``fixtures/agy_validator_corpus/``) runs
  the validator entry points -- ``validate_records``, ``validate_directory`` and
  ``_classify_failure`` -- over one passing case and the failing cases of each pass predicate,
  and pins ``{QUALIFICATION_VALIDATOR: sha256(verdict vector)}``. A verdict-changing edit
  anywhere in their transitive closure, ``panel_invoker.terminal_verdict`` and the prompt and
  stream helpers included, turns it red unless the literal is bumped (and re-pinned);
- the **source-hash table** (supplement): the AST call-graph closure of the entry points
  (``scripts/convert_agy_record_v2.py``) is pinned, so an edit that keeps every verdict still
  asks for a deliberate review.

The corpus series is a conforming stand-in run of the production driver (no provider data).
"""
from __future__ import annotations

import copy
import dataclasses
import importlib.util
import inspect
import json
import shutil
import tempfile
import textwrap
from hashlib import sha256
from pathlib import Path

import pytest

from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker as pi

CORPUS = Path(__file__).resolve().parent / "fixtures" / "agy_validator_corpus"
SERIES = CORPUS / "series"
CONVERTER = Path(__file__).resolve().parents[1] / "scripts" / "convert_agy_record_v2.py"

#: The verdict vector each validator literal means. A bump adds a row; it never edits one.
VERDICT_VECTOR_SHA256 = {
    "agy_validator_v1": "41e4966fa9c43da15878509c9df968599451de99986d60cc802081cde1c270f4",
}
#: The validator's source-hash closure per literal (the supplement). An edit that keeps every
#: verdict updates this pin in a reviewed change; one that changes a verdict bumps the literal.
VALIDATOR_CLOSURE_SHA256 = {
    "agy_validator_v1": "6379dbc3ec93689d4802634811fc9d3539803354b2b3483fdbb1e382222b715c",
}


# --------------------------------------------------------------------------- QCI

def test_seat_qci_is_the_profile_digest_at_v1():
    assert q.QUALIFICATION_VALIDATOR == "agy_validator_v1"
    assert q.seat_qci() == q.agy_profile_digest()


def test_seat_qci_ignores_the_runtime_version(monkeypatch):
    import phase_loop_runtime

    before = q.seat_qci()
    monkeypatch.setattr(phase_loop_runtime, "__version__", "99.0.0")
    monkeypatch.setattr(q, "__version__", "99.0.0")
    assert q.seat_qci() == before


def test_seat_qci_ignores_a_catalog_edit(monkeypatch, tmp_path):
    before = q.seat_qci()
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {"a" * 64: "b" * 64})
    assert q.seat_qci() == before
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", gh.load_catalog(tmp_path / "absent.json"))
    assert q.seat_qci() == before


def test_seat_qci_changes_with_the_operations_contract(monkeypatch):
    before = q.seat_qci()
    first, *rest = q.OPERATIONS_CONTRACT
    monkeypatch.setattr(q, "OPERATIONS_CONTRACT", (first._replace(env_names=first.env_names + ("EXTRA",)), *rest))
    assert q.seat_qci() != before


@pytest.mark.parametrize("edit", ["profile_id", "settings"])
def test_seat_qci_changes_with_the_owned_profile(monkeypatch, edit):
    before = q.seat_qci()
    if edit == "profile_id":
        monkeypatch.setattr(gh, "PROFILE_ID", "agy_memfd_home_deny_all_v2")
    else:
        real = pi._broker_agy_settings_bytes
        monkeypatch.setattr(pi, "_broker_agy_settings_bytes", lambda: real() + b" ")
    assert q.seat_qci() != before


def test_seat_qci_changes_with_the_validator_literal(monkeypatch):
    before = q.seat_qci()
    monkeypatch.setattr(q, "QUALIFICATION_VALIDATOR", "agy_validator_v2")
    assert q.seat_qci() != before and q.agy_profile_digest() == before


# ------------------------------------------------------------- the semantic guard

def _expected():
    return json.loads((CORPUS / "expected.json").read_text())


def _cases():
    return json.loads((CORPUS / "cases.json").read_text())


def _base(operation):
    return json.loads((SERIES / operation / "qualification.json").read_text())


_DELETE = "$delete"


def _apply(value, path, item):
    target = value
    for key in path[:-1]:
        target = target[key]
    if item == _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = item


def _record_case(case):
    record = copy.deepcopy(_base(case["operation"]))
    for path, item in case.get("set", []):
        _apply(record, path, item)
        if path == ["result", "text"] and isinstance(item, str) and record.get("broker"):
            record["broker"]["provider_response_sha256"] = sha256(item.encode()).hexdigest()
    if case.get("rehash", True):
        record["record_sha256"] = {name: q.digest(record[name])
                                   for name in ("monitoring", "broker", "observer", "result") if name in record}
    return record


def _directory_case(case, root):
    shutil.copytree(SERIES, root)
    for operation in case.get("drop", []):
        shutil.rmtree(root / operation)
    for name, text in case.get("append", {}).items():
        with (root / name).open("a") as handle:
            handle.write(text)
    for name, changes in case.get("json", {}).items():
        value = json.loads((root / name).read_text())
        for path, item in changes:
            _apply(value, path, item)
        (root / name).write_text(json.dumps(value))
    return root


_SINGLE_PROMPT = "agy validator corpus: one sealed review prompt that fits a single chunk"


def _protocol(kind):
    if kind == "single":
        return pi._broker_gemini_stream_protocol(_SINGLE_PROMPT)
    # two chunks, so the ingestion acknowledgements are exercised
    return pi._broker_gemini_stream_protocol("x" * (pi._BROKER_AGY_STREAM_CHUNK_MAX_BYTES + 1024))


def _stream_text(case, protocol):
    lines = []
    for line in case["lines"]:
        if line.startswith("$ACK"):
            index, _, status = line[4:].partition(":")
            lines.append(json.dumps({"event": "result", "result": {
                "status": status or "SUCCESS", "conversation_id": "c1",
                "response": protocol.acknowledgements[int(index) - 1]}}))
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def verdict_vector(tmp_path):
    """Every corpus case through the production entry points, in corpus order."""
    tmp_path = Path(tempfile.mkdtemp(dir=tmp_path))
    expected, cases, vector = _expected(), _cases(), []
    for case in cases["records"]:
        try:
            q.validate_records(_record_case(case), **expected)
            verdict = "pass"
        except q.QualificationFailure:
            verdict = "reject"
        except Exception as exc:  # noqa: BLE001 - pinned: what escapes the validator is part of its meaning
            verdict = "raise:" + type(exc).__name__
        vector.append([case["id"], verdict])
    for index, case in enumerate(cases["directory"]):
        root = _directory_case(case, tmp_path / f"directory-{index}")
        try:
            verdict = "pass:" + str(q.validate_directory(root, **expected)["route_qualified"]).lower()
        except (q.QualificationFailure, OSError, ValueError, KeyError):
            verdict = "reject"
        vector.append([case["id"], verdict])
    for index, case in enumerate(cases["classify"]):
        root = tmp_path / f"classify-{index}"
        root.mkdir()
        for name in ("failure", "terminal"):
            if case.get(name) is not None:
                (root / f"{name}.json").write_text(json.dumps(case[name]))
        vector.append([case["id"], q._classify_failure(root, case["operation"])])
    for case in cases["stream"]:
        # The stream parser decides the outcome the broker records (agent-harness#1937 B1).
        protocol = _protocol(case["protocol"])
        try:
            code, _text, _diagnostic, metadata = pi._broker_gemini_stream_result(_stream_text(case, protocol), protocol)
            verdict = f"{code}:{metadata['provider_stream_outcome']}"
        except Exception as exc:  # noqa: BLE001 - pinned like the record cases
            verdict = "raise:" + type(exc).__name__
        vector.append([case["id"], verdict])
    return vector


def vector_sha256(vector):
    return sha256(json.dumps(vector, separators=(",", ":")).encode()).hexdigest()


def guard_holds(tmp_path) -> bool:
    return VERDICT_VECTOR_SHA256.get(q.QUALIFICATION_VALIDATOR) == vector_sha256(verdict_vector(tmp_path))


def test_the_corpus_covers_every_pass_predicate(tmp_path):
    cases = _cases()
    ids = [case["id"] for section in cases.values() for case in section]
    assert len(ids) == len(set(ids))
    verdicts = dict(verdict_vector(tmp_path))
    for operation in q.OPERATIONS:
        mine = [case["id"] for case in cases["records"] if case["operation"] == operation]
        assert any(verdicts[name] == "pass" for name in mine), operation
        assert sum(verdicts[name] == "reject" for name in mine) >= 3, operation
    assert {verdicts[case["id"]] for case in cases["classify"]} == {"failed", "transient"}
    assert {verdicts[case["id"]] for case in cases["directory"]} >= {"pass:true", "pass:false", "reject"}
    stream = {verdicts[case["id"]] for case in cases["stream"]}
    assert "0:accepted" in stream and len(stream - {"0:accepted"}) >= 5
    # each case states the verdict it was written for; the vector must agree with every one
    assert {case["id"]: case["expect"] for section in cases.values() for case in section} == verdicts


def test_the_guard_holds_at_this_validator(tmp_path):
    assert guard_holds(tmp_path), vector_sha256(verdict_vector(tmp_path))


def _terminal_verdict_accepts_anything(monkeypatch):
    monkeypatch.setattr(pi, "terminal_verdict", lambda text: "AGREE")


def _terminal_verdict_reads_the_first_line(monkeypatch):
    real = pi.terminal_verdict
    monkeypatch.setattr(pi, "terminal_verdict", lambda text: real((text or "").splitlines()[0] if text else text))


def _prompt_renders_differently(monkeypatch):
    real = pi._render_broker_inline_prompt
    monkeypatch.setattr(pi, "_render_broker_inline_prompt", lambda *a, **k: real(*a, **k) + "\n")


def _stream_transport_differs(monkeypatch):
    real = pi._broker_gemini_stream_protocol

    def mutated(prompt, **kwargs):
        protocol = real(prompt, **kwargs)
        return dataclasses.replace(protocol, transport=protocol.transport + "\n")
    monkeypatch.setattr(pi, "_broker_gemini_stream_protocol", mutated)


def _model_hardening_differs(monkeypatch):
    monkeypatch.setattr(q, "_harden_subscription_model", lambda *args: "gemini-mutant")


def _transients_are_violations(monkeypatch):
    monkeypatch.setattr(q, "_TRANSIENT_REASONS", frozenset())


def _profile_id_differs(monkeypatch):
    monkeypatch.setattr(gh, "PROFILE_ID", "agy_memfd_home_deny_all_mutant")


def _argv_render_differs(monkeypatch):
    real = q.render_operation_argv
    monkeypatch.setattr(q, "render_operation_argv", lambda operation, model: real(operation, model)[:-1] + ["1"])


def _source_mutant(monkeypatch, module, name, old, new):
    """Recompile one function with one edit, the way a source change would land."""
    source = textwrap.dedent(inspect.getsource(getattr(module, name)))
    assert source.count(old) == 1, (name, old)
    namespace = dict(module.__dict__)
    exec(compile(source.replace(old, new), module.__file__, "exec"), namespace)  # noqa: S102
    monkeypatch.setattr(module, name, namespace[name])


def _stream_final_success_check_removed(monkeypatch):
    _source_mutant(monkeypatch, pi, "_broker_gemini_stream_result",
                   'if final.get("status") != "SUCCESS" or not isinstance(final.get("response"), str):',
                   'if not isinstance(final.get("response"), str):')


def _image_readonly_predicate_removed(monkeypatch):
    _source_mutant(monkeypatch, q, "validate_records",
                   'for key in ("image_readonly", "home_removed",', 'for key in ("home_removed",')


def _registry_lets_gemini_run_any_model(monkeypatch):
    from phase_loop_runtime.advisor_board import registries

    monkeypatch.setattr(registries, "_MODEL_SPECS", tuple(
        dataclasses.replace(spec, runnable_by=tuple(dict.fromkeys((*spec.runnable_by, "gemini"))))
        for spec in registries._MODEL_SPECS))


MUTANTS = {
    "panel_invoker._broker_gemini_stream_result drops the final SUCCESS check": _stream_final_success_check_removed,
    "agy_qualification.validate_records drops the image_readonly predicate": _image_readonly_predicate_removed,
    "advisor_board.registries lets gemini run another harness's model": _registry_lets_gemini_run_any_model,
    "panel_invoker.terminal_verdict accepts a non-terminal stream": _terminal_verdict_accepts_anything,
    "panel_invoker.terminal_verdict reads the first line": _terminal_verdict_reads_the_first_line,
    "panel_invoker._render_broker_inline_prompt": _prompt_renders_differently,
    "panel_invoker._broker_gemini_stream_protocol": _stream_transport_differs,
    "advisor_board model hardening": _model_hardening_differs,
    "agy_qualification._TRANSIENT_REASONS": _transients_are_violations,
    "gemini_heartbeat.PROFILE_ID": _profile_id_differs,
    "agy_qualification.render_operation_argv": _argv_render_differs,
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_verdict_changing_mutant_turns_the_guard_red_without_a_bump(tmp_path, monkeypatch, name):
    MUTANTS[name](monkeypatch)
    assert q.QUALIFICATION_VALIDATOR == "agy_validator_v1"
    assert not guard_holds(tmp_path)


def test_a_literal_bump_needs_its_own_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "QUALIFICATION_VALIDATOR", "agy_validator_v2")
    assert not guard_holds(tmp_path)


def _converter():
    spec = importlib.util.spec_from_file_location("convert_agy_record_v2_for_qci", CONVERTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not CONVERTER.is_file(), reason="the converter is repository source")
def test_the_validator_closure_is_pinned():
    converter = _converter()
    table = converter.validator_closure(Path(q.__file__).resolve().parent)
    assert VALIDATOR_CLOSURE_SHA256.get(q.QUALIFICATION_VALIDATOR) == converter.closure_digest(table), \
        converter.closure_digest(table)


@pytest.mark.skipif(not CONVERTER.is_file(), reason="the converter is repository source")
@pytest.mark.parametrize(("relative", "old", "new"), [
    # reached only through advisor_board.backing's relative imports (agent-harness#1937 B2)
    ("advisor_board/registries.py",
     "return tuple(s.name for s in _HARNESS_SPECS if vendor_of_harness(s.name) == model_vendor)",
     'return tuple(s.name for s in _HARNESS_SPECS if vendor_of_harness(s.name) == model_vendor or s.name == "gemini")'),
    ("panel_invoker.py",
     'if final.get("status") != "SUCCESS" or not isinstance(final.get("response"), str):',
     'if not isinstance(final.get("response"), str):'),
    ("agy_qualification.py", 'for key in ("image_readonly", "home_removed",', 'for key in ("home_removed",'),
])
def test_a_source_edit_in_the_transitive_closure_changes_its_digest(tmp_path, relative, old, new):
    converter = _converter()
    package = Path(q.__file__).resolve().parent
    copy = tmp_path / "phase_loop_runtime"
    shutil.copytree(package, copy, ignore=shutil.ignore_patterns("__pycache__"))
    path = copy / relative
    text = path.read_text()
    assert text.count(old) == 1
    path.write_text(text.replace(old, new))
    assert converter.validator_closure(copy) != converter.validator_closure(package)
