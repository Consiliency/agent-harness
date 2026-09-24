"""Frozen EXECFIND tests-first corpus and receipt-soundness checks."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import execfind_content_tdd_adapter as tdd
from phase_loop_runtime import panel_invoker as pi


GOLDEN = Path(__file__).parent / "data/execfind_falsifier_attachment_v1.golden.json"


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _falsifier_text(entry, *, nodeid=None, diff=None, include_nodeid=True, repeat=False):
    node_line = f"nodeid: {entry['expected_nodeid'] if nodeid is None else nodeid}\n"
    block = "```falsifier\n" + (node_line if include_nodeid else "")
    block += (entry["diff"] if diff is None else diff) + "```\n"
    return "FINDING F001: BLOCKING — runnable reproduction\n" + block * (2 if repeat else 1) + "DISAGREE\n"


def _canonical_red_output():
    return (
        "\n".join(f"{tdd.RED_ANCHOR_MARKER} EXECFIND_RED::{case}" for case in tdd.EXPECTED_RED_CASES)
        + "\n"
        + "\n".join(f"FAILED {node}" for node in sorted(tdd.EXPECTED_RED_NODES))
        + f"\n{len(tdd.EXPECTED_RED_NODES)} failed, 9 passed in 1.00s\n"
    )


def _receipt(*, files=None, nodes=None, stdout="red.stdout.log", stderr="red.stderr.log"):
    return SimpleNamespace(
        test_files=tuple((name, "a" * 64) for name in (tdd.FROZEN_FILES if files is None else files)),
        red_nodeids=tuple(tdd.EXPECTED_RED_NODES if nodes is None else nodes),
        red_stdout_path=stdout,
        red_stderr_path=stderr,
        landing_commit="f" * 40,
    )


def test_unexpected_pass_refused(monkeypatch):
    monkeypatch.setenv(tdd.ACTIVATION_ENV, "1")
    with pytest.raises(AssertionError, match=tdd.UNSOUND) as error:
        tdd.run_execfind_contract("grammar", lambda: None)
    assert tdd.RED_ANCHOR_MARKER not in str(error.value)
    assert tdd.scan_red_output(_canonical_red_output() + tdd.UNSOUND) is not None


def test_marker_exact_match_only():
    valid = _canonical_red_output()
    assert tdd.scan_red_output(valid) is None
    mutated = valid.replace("EXECFIND_RED::grammar\n", "EXECFIND_RED::grammar_extra\n")
    assert "markers" in tdd.scan_red_output(mutated)
    repeated = valid + f"\n{tdd.RED_ANCHOR_MARKER} EXECFIND_RED::grammar\n"
    assert "markers" in tdd.scan_red_output(repeated)


def test_unrelated_exception_propagates(monkeypatch):
    monkeypatch.setenv(tdd.ACTIVATION_ENV, "1")

    def broken():
        raise RuntimeError("genuine contract error")

    with pytest.raises(RuntimeError, match="genuine contract error"):
        tdd.run_execfind_contract("grammar", broken)


def test_importerror_not_capability_absence(monkeypatch):
    def broken_dependency(_name):
        raise ModuleNotFoundError("nested dependency absent", name="nested_dependency")

    monkeypatch.setattr(tdd.importlib, "import_module", broken_dependency)
    with pytest.raises(ModuleNotFoundError) as error:
        tdd.require_module("phase_loop_runtime.falsifier")
    assert error.value.name == "nested_dependency"


def test_rejected_recording_no_receipt(tmp_path, monkeypatch):
    def fake_recorder(**kwargs):
        staged = kwargs["out"]
        staged.write_text("{}")
        (staged.parent / "red.stdout.log").write_text(tdd.UNSOUND)
        (staged.parent / "red.stderr.log").write_text("")
        return _receipt()

    monkeypatch.setattr(tdd, "record_content_tdd_receipt", fake_recorder)
    receipt_path = tmp_path / "evidence" / "receipt.json"
    assert tdd.record_red(tmp_path, "HEAD", receipt_path) == 1
    assert not receipt_path.exists()


def test_verify_rescans_red_log(tmp_path, monkeypatch):
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text("{}")
    (tmp_path / "red.stdout.log").write_text(_canonical_red_output() + tdd.UNSOUND)
    (tmp_path / "red.stderr.log").write_text("")
    monkeypatch.setattr(tdd, "verify_content_tdd_receipt", lambda **_kwargs: _receipt())
    assert tdd.verify(tmp_path, None, receipt_path) == 2


def test_every_expected_case_ran():
    valid = _canonical_red_output()
    missing_node = next(iter(tdd.EXPECTED_RED_NODES))
    mutated = valid.replace(f"FAILED {missing_node}\n", "")
    assert "nodes differ" in tdd.scan_red_output(mutated)
    collection_error = "ERROR collecting test_execfind_falsifier.py\n1 error in 1.00s\n"
    assert tdd.scan_red_output(collection_error) is not None


def test_red_output_digest_golden():
    golden = _golden()
    fixture = golden["red_output_fixture"]
    digest = hashlib.sha256(
        fixture["stdout_utf8"].encode("utf-8") + fixture["stderr_utf8"].encode("utf-8")
    ).hexdigest()
    assert digest == golden["record"]["red_output_digest"]
    record_digest = hashlib.sha256(json.dumps(
        golden["record"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    assert record_digest == golden["record_digest"]


def test_frozen_inventory_exact():
    assert tdd.scan_inventory(_receipt()) is None
    missing = set(tdd.FROZEN_FILES) - {tdd.FROZEN_TEST_FILES[1]}
    assert "inventory" in tdd.scan_inventory(_receipt(files=missing))
    missing_node = set(tdd.EXPECTED_RED_NODES) - {next(iter(tdd.EXPECTED_RED_NODES))}
    assert "node id" in tdd.scan_inventory(_receipt(nodes=missing_node))


def test_outcome_vocabulary():
    def check():
        module = tdd.require_module("phase_loop_runtime.falsifier")
        assert tuple(tdd.require_attr(module, "FALSIFIER_OUTCOMES")) == tuple(
            _golden()["outcomes"]
        )

    tdd.run_execfind_contract("outcome_vocabulary", check)


def test_grammar():
    def check():
        entry = _golden()["attachment"]["falsifiers"][0]
        text = _falsifier_text(entry)
        attachment = tdd.require_attr(pi, "parse_finding_falsifiers")(text)
        assert asdict(attachment) == _golden()["attachment"]
        assert pi.terminal_verdict(text) == "DISAGREE"

    tdd.run_execfind_contract("grammar", check)


def test_parser_reject_outside_tests():
    def check():
        entry = _golden()["attachment"]["falsifiers"][0]
        outside = "phase-loop-runtime/src/phase_loop_runtime/unsafe.py"
        altered = entry["diff"].replace(entry["new_test_path"], outside)
        parser = tdd.require_attr(pi, "parse_finding_falsifiers")
        with pytest.raises(ValueError):
            parser(_falsifier_text(entry, nodeid=f"{outside}::test_trigger", diff=altered))

    tdd.run_execfind_contract("parser_reject_outside_tests", check)


def test_parser_reject_modify_existing():
    def check():
        entry = _golden()["attachment"]["falsifiers"][0]
        altered = entry["diff"].replace("new file mode 100644\n--- /dev/null\n", "--- a/phase-loop-runtime/tests/test_finding_F001.py\n")
        parser = tdd.require_attr(pi, "parse_finding_falsifiers")
        with pytest.raises(ValueError):
            parser(_falsifier_text(entry, diff=altered))

    tdd.run_execfind_contract("parser_reject_modify_existing", check)


def test_parser_reject_no_nodeid():
    def check():
        entry = _golden()["attachment"]["falsifiers"][0]
        parser = tdd.require_attr(pi, "parse_finding_falsifiers")
        with pytest.raises(ValueError):
            parser(_falsifier_text(entry, include_nodeid=False))

    tdd.run_execfind_contract("parser_reject_no_nodeid", check)


def test_parser_reject_foreign_nodeid():
    def check():
        entry = _golden()["attachment"]["falsifiers"][0]
        parser = tdd.require_attr(pi, "parse_finding_falsifiers")
        with pytest.raises(ValueError):
            parser(_falsifier_text(entry, nodeid="phase-loop-runtime/tests/test_other.py::test_trigger"))

    tdd.run_execfind_contract("parser_reject_foreign_nodeid", check)


def test_parser_reject_double_claim():
    def check():
        entry = _golden()["attachment"]["falsifiers"][0]
        parser = tdd.require_attr(pi, "parse_finding_falsifiers")
        with pytest.raises(ValueError):
            parser(_falsifier_text(entry, repeat=True))

    tdd.run_execfind_contract("parser_reject_double_claim", check)


def test_brief_teaches_form():
    def check():
        tdd.require_attr(pi, "FindingFalsifier")
        brief = pi._REVIEW_INSTRUCTIONS.lower()
        assert "falsifier" in brief
        assert "nodeid:" in brief
        assert "phase-loop-runtime/tests/test_finding_" in brief
        assert "```falsifier" in brief
        assert pi._mode_instructions("review") == pi._REVIEW_INSTRUCTIONS
        assert pi.terminal_verdict("FINDING F001: BLOCKING — repro\nDISAGREE") == "DISAGREE"

    tdd.run_execfind_contract("brief_teaches_form", check)


def test_attachment_byte_neutral():
    def check():
        entry = _golden()["attachment"]["falsifiers"][0]
        falsifier = tdd.require_attr(pi, "FindingFalsifier")(**entry)
        attachment = tdd.require_attr(pi, "FindingFalsifierAttachment")((falsifier,))
        attach = tdd.require_attr(pi, "attach_finding_falsifiers")
        leg = pi.PanelLegResult("claude", "OK", "FINDING F001: BLOCKING — repro\nDISAGREE")
        before = asdict(leg)
        assert attach(leg, attachment) is leg
        assert asdict(leg) == before
        assert leg.finding_falsifiers == attachment
        assert pi.PanelLegResult("claude", "OK").finding_falsifiers is None

    tdd.run_execfind_contract("attachment_byte_neutral", check)


def test_attachment_matches_frozen_contract():
    def check():
        golden = _golden()
        entry = golden["attachment"]["falsifiers"][0]
        falsifier = tdd.require_attr(pi, "FindingFalsifier")(**entry)
        attachment = tdd.require_attr(pi, "FindingFalsifierAttachment")((falsifier,))
        assert is_dataclass(falsifier) and set(asdict(falsifier)) == {
            "finding_id", "new_test_path", "expected_nodeid", "diff",
        }
        assert is_dataclass(attachment) and set(asdict(attachment)) == {"falsifiers"}
        assert asdict(attachment) == golden["attachment"]
        record = golden["record"]
        assert set(record) == {
            "schema", "authorization_identity", "seat_key", "reviewed_sha", "finding_id",
            "nodeid", "outcome", "red_output_digest", "diff_digest", "wall_clock_bound_s",
            "output_cap_bytes",
        }
        assert record["schema"] == "finding_falsifier.v1"
        assert record["authorization_identity"] == "public_board_falsifier.v1"
        assert type(record["seat_key"]) is str and bool(record["seat_key"])
        assert type(record["reviewed_sha"]) is str and len(record["reviewed_sha"]) == 40
        assert type(record["wall_clock_bound_s"]) is float
        assert type(record["output_cap_bytes"]) is int
        assert hashlib.sha256(falsifier.diff.encode("utf-8")).hexdigest() == record["diff_digest"]
        assert hashlib.sha256(
            golden["red_output_fixture"]["stdout_utf8"].encode("utf-8")
            + golden["red_output_fixture"]["stderr_utf8"].encode("utf-8")
        ).hexdigest() == record["red_output_digest"]
        module = tdd.require_module("phase_loop_runtime.falsifier")
        assert tuple(tdd.require_attr(module, "FALSIFIER_OUTCOMES")) == tuple(golden["outcomes"])
        result = tdd.require_attr(module, "FalsifierRunResult")(
            outcome=record["outcome"], nodeid=record["nodeid"],
            red_output_digest=record["red_output_digest"], diff_digest=record["diff_digest"],
            junit_path=None, detail=None, record=record,
        )
        assert is_dataclass(result) and set(asdict(result)) == {
            "outcome", "nodeid", "red_output_digest", "diff_digest", "junit_path",
            "detail", "record",
        }
        assert result.record == record
        record_digest = hashlib.sha256(json.dumps(
            result.record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        assert record_digest == golden["record_digest"]
        governed = tdd.require_module("phase_loop_runtime.governed_review")
        binding = tdd.require_attr(governed, "FalsifierRunBinding")(
            seat_key=record["seat_key"], finding_id=record["finding_id"],
            reviewed_sha=record["reviewed_sha"], result=result,
            record_digest=record_digest,
        )
        assert is_dataclass(binding) and set(asdict(binding)) == {
            "seat_key", "finding_id", "reviewed_sha", "result", "record_digest",
        }
        assert (binding.seat_key, binding.finding_id, binding.reviewed_sha) == (
            record["seat_key"], record["finding_id"], record["reviewed_sha"],
        )

    tdd.run_execfind_contract("attachment_matches_frozen_contract", check)
