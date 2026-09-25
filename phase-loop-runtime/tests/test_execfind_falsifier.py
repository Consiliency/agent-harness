"""Frozen EXECFIND tests-first corpus and receipt-soundness checks."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
import hashlib
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest

import execfind_content_tdd_adapter as tdd
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import review_stage
from phase_loop_runtime.advisor_board import backing


GOLDEN = Path(__file__).parent / "data/execfind_falsifier_attachment_v1.golden.json"


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _falsifier_text(entry, *, nodeid=None, diff=None, include_nodeid=True, repeat=False):
    node_line = f"nodeid: {entry['expected_nodeid'] if nodeid is None else nodeid}\n"
    block = "```falsifier\n" + (node_line if include_nodeid else "")
    block += (entry["diff"] if diff is None else diff) + "```\n"
    return "FINDING F001: BLOCKING — runnable reproduction\n" + block * (2 if repeat else 1) + "DISAGREE\n"


def _source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "execfind@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "EXECFIND test"], check=True)
    (repo / ".gitignore").write_text("ignored-extra.tmp\n", encoding="utf-8")
    (repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "target_a.txt").write_text("a\n", encoding="utf-8")
    (repo / "target_b.txt").write_text("b\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("target_a.txt")
    script = repo / "script.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    (repo / "phase-loop-runtime" / "tests").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "base"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    return repo, head


def _test_diff(source):
    entry = _golden()["attachment"]["falsifiers"][0]
    lines = source.strip("\n").splitlines()
    return (
        f"diff --git a/{entry['new_test_path']} b/{entry['new_test_path']}\n"
        "new file mode 100644\n--- /dev/null\n"
        f"+++ b/{entry['new_test_path']}\n@@ -0,0 +1,{len(lines)} @@\n"
        + "".join(f"+{line}\n" for line in lines)
    )


def _run_falsifier(repo, head, *, source=None, diff=None, nodeid=None, wall_clock_s=30.0,
                   output_cap_bytes=65536):
    module = tdd.require_module("phase_loop_runtime.falsifier")
    run = tdd.require_attr(module, "run_finding_falsifier")
    mint = tdd.require_attr(backing, "prepare_falsifier_isolation_authorization")
    entry = dict(_golden()["attachment"]["falsifiers"][0])
    if source is not None:
        entry["diff"] = _test_diff(source)
    if diff is not None:
        entry["diff"] = diff
    if nodeid is not None:
        entry["expected_nodeid"] = nodeid
    falsifier = tdd.require_attr(pi, "FindingFalsifier")(**entry)
    authorization = mint(repo=repo, reviewed_sha=head)
    result = run(
        falsifier=falsifier, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=wall_clock_s,
        output_cap_bytes=output_cap_bytes,
    )
    return result, authorization


def _mutate_stage(monkeypatch, mutate, *, before=False):
    module = tdd.require_module("phase_loop_runtime.falsifier")
    original = review_stage.stage_review_tree

    def changed(repo, *args, **kwargs):
        if before:
            mutate(Path(repo))
        staged = original(repo, *args, **kwargs)
        if not before:
            mutate(Path(staged))
        return staged

    monkeypatch.setattr(review_stage, "stage_review_tree", changed)
    if hasattr(module, "stage_review_tree"):
        monkeypatch.setattr(module, "stage_review_tree", changed)


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
    collected = {node.removeprefix("phase-loop-runtime/") for node in tdd.EXPECTED_RED_NODES}
    assert tdd.scan_inventory(_receipt(nodes=collected)) is None
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


def test_apply_failed(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        modifying_existing = (
            "diff --git a/module.py b/module.py\n--- a/module.py\n+++ b/module.py\n"
            "@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
        )
        result, _ = _run_falsifier(repo, head, diff=modifying_existing)
        assert result.outcome == "apply_failed"
        assert (repo / "module.py").read_text() == "VALUE = 1\n"

    tdd.run_execfind_contract("apply_failed", check)


def test_red_on_head(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        result, _ = _run_falsifier(repo, head)
        assert result.outcome == "red_on_head"
        assert result.nodeid == _golden()["record"]["nodeid"]
        assert result.record["reviewed_sha"] == head
        assert result.record["red_output_digest"] == result.red_output_digest
        assert result.red_output_digest and len(result.red_output_digest) == 64
        assert not (repo / "phase-loop-runtime/tests/test_finding_F001.py").exists()

    tdd.run_execfind_contract("red_on_head", check)


def test_green_on_head(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        result, _ = _run_falsifier(repo, head, source="def test_trigger():\n    assert True\n")
        assert result.outcome == "green_on_head"
        assert result.red_output_digest is None
        assert result.record["red_output_digest"] is None

    tdd.run_execfind_contract("green_on_head", check)


def test_node_missing(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        result, _ = _run_falsifier(repo, head, source="def test_other():\n    assert False\n")
        assert result.outcome == "node_missing"
        assert result.red_output_digest is None

    tdd.run_execfind_contract("node_missing", check)


def test_bound_expiry_error(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        slow = "import time\ndef test_trigger():\n    time.sleep(2)\n    assert False\n"
        expired, _ = _run_falsifier(repo, head, source=slow, wall_clock_s=0.01)
        assert expired.outcome == "error"
        assert expired.red_output_digest is None
        noisy = "def test_trigger():\n    print('x' * 10000)\n    assert False\n"
        capped, _ = _run_falsifier(repo, head, source=noisy, output_cap_bytes=128)
        assert capped.outcome == "error"
        assert capped.red_output_digest is None

    tdd.run_execfind_contract("bound_expiry_error", check)


def test_no_network_no_credentials(tmp_path, monkeypatch):
    def check():
        repo, head = _source_repo(tmp_path)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            monkeypatch.setenv("EXECFIND_TEST_SECRET", "parent-only-canary")
            source = (
                "import os\nimport socket\nimport pytest\n"
                "def test_trigger():\n"
                "    assert os.getenv('EXECFIND_TEST_SECRET') is None\n"
                "    with pytest.raises(OSError):\n"
                f"        socket.create_connection(('127.0.0.1', {port}), timeout=1)\n"
            )
            result, authorization = _run_falsifier(repo, head, source=source)
        assert result.outcome == "green_on_head"
        assert authorization.child_credentialless is True
        assert authorization.child_network_egress is False
        assert authorization.live_tree_exposed is False

    tdd.run_execfind_contract("no_network_no_credentials", check)


def test_staged_tree_only(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        source = (
            "from pathlib import Path\n"
            "def test_trigger():\n"
            "    Path('falsifier-ran.marker').write_text('stage only')\n"
            "    assert True\n"
        )
        result, _ = _run_falsifier(repo, head, source=source)
        assert result.outcome == "green_on_head"
        assert not (repo / "falsifier-ran.marker").exists()
        assert not (repo / "phase-loop-runtime/tests/test_finding_F001.py").exists()

    tdd.run_execfind_contract("staged_tree_only", check)


def test_staged_overlay_drift_error(tmp_path, monkeypatch):
    def check():
        repo, head = _source_repo(tmp_path)
        _mutate_stage(
            monkeypatch,
            lambda source: (source / "module.py").write_text("VALUE = 2\n"),
            before=True,
        )
        result, _ = _run_falsifier(repo, head)
        assert result.outcome == "error"
        assert result.red_output_digest is None
        assert not (repo / "phase-loop-runtime/tests/test_finding_F001.py").exists()

    tdd.run_execfind_contract("staged_overlay_drift_error", check)


def test_staged_untracked_extra_error(tmp_path, monkeypatch):
    def check():
        repo, head = _source_repo(tmp_path)
        _mutate_stage(monkeypatch, lambda stage: (stage / "extra.tmp").write_text("extra"))
        result, _ = _run_falsifier(repo, head)
        assert result.outcome == "error"
        assert not (repo / "extra.tmp").exists()

    tdd.run_execfind_contract("staged_untracked_extra_error", check)


def test_staged_ignored_extra_error(tmp_path, monkeypatch):
    def check():
        repo, head = _source_repo(tmp_path)
        _mutate_stage(
            monkeypatch, lambda stage: (stage / "ignored-extra.tmp").write_text("ignored")
        )
        result, _ = _run_falsifier(repo, head)
        assert result.outcome == "error"

    tdd.run_execfind_contract("staged_ignored_extra_error", check)


def test_staged_symlink_retarget_error(tmp_path, monkeypatch):
    def check():
        repo, head = _source_repo(tmp_path)

        def retarget(stage):
            (stage / "link.txt").unlink()
            (stage / "link.txt").symlink_to("target_b.txt")

        _mutate_stage(monkeypatch, retarget)
        result, _ = _run_falsifier(repo, head)
        assert result.outcome == "error"

    tdd.run_execfind_contract("staged_symlink_retarget_error", check)


def test_staged_exec_bit_drift_error(tmp_path, monkeypatch):
    def check():
        repo, head = _source_repo(tmp_path)
        _mutate_stage(monkeypatch, lambda stage: (stage / "script.sh").chmod(0o644))
        result, _ = _run_falsifier(repo, head)
        assert result.outcome == "error"

    tdd.run_execfind_contract("staged_exec_bit_drift_error", check)


def test_only_named_node_runs(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        source = (
            "import os\n"
            "def test_trigger():\n    assert False\n"
            "def test_other():\n    os._exit(31)\n"
        )
        result, _ = _run_falsifier(repo, head, source=source)
        assert result.outcome == "red_on_head"
        assert result.nodeid.endswith("::test_trigger")

    tdd.run_execfind_contract("only_named_node_runs", check)


def test_authorization_identity(tmp_path):
    def check():
        repo, head = _source_repo(tmp_path)
        module = tdd.require_module("phase_loop_runtime.falsifier")
        run = tdd.require_attr(module, "run_finding_falsifier")
        mint = tdd.require_attr(backing, "prepare_falsifier_isolation_authorization")
        entry = _golden()["attachment"]["falsifiers"][0]
        falsifier = tdd.require_attr(pi, "FindingFalsifier")(**entry)
        authorization = mint(repo=repo, reviewed_sha=head)
        assert authorization.operation == "public_board_falsifier.v1"
        assert authorization.reviewed_sha == head
        assert authorization.child_credentialless is True
        assert authorization.child_network_egress is False
        assert authorization.live_tree_exposed is False
        with pytest.raises(ValueError):
            run(
                falsifier=falsifier, seat_key="claude:claude-opus-5-5:max:correctness",
                authorization=replace(authorization, _seal=object()), repo=repo,
                wall_clock_s=30.0, output_cap_bytes=65536,
            )

    tdd.run_execfind_contract("authorization_identity", check)


def test_seat_tool_attempt_refused():
    def check():
        tdd.require_attr(pi, "FindingFalsifier")
        command = pi._broker_claude_tui_command(
            model="claude-opus-5-5", effort="high",
            session_id="00000000-0000-4000-8000-000000000001",
        )
        assert command[command.index("--tools") + 1] == ""
        assert command[command.index("--allowedTools") + 1] == ""
        assert "Bash" in command[command.index("--disallowedTools") + 1]
        assert "command(*)" in pi._BROKER_AGY_DENY_ACTIONS
        assert "read_file(*)" in pi._BROKER_AGY_DENY_ACTIONS

    tdd.run_execfind_contract("seat_tool_attempt_refused", check)


def test_inline_fixture_artifact_ref(tmp_path):
    def check():
        tdd.require_attr(pi, "FindingFalsifier")
        bundle = tmp_path / "review.md"
        fixture = tmp_path / "finding-fixture.py"
        bundle.write_text("Review F001 against this artifact.\n", encoding="utf-8")
        fixture.write_text("def test_trigger():\n    assert False\n", encoding="utf-8")
        resolved = pi._resolve_artifact(None, [str(bundle), str(fixture)])
        assert resolved.index("Review F001") < resolved.index("def test_trigger")
        assert "## review.md" in resolved and "## finding-fixture.py" in resolved
        assert "def test_trigger" in pi._render_broker_inline_prompt(
            resolved, "Review the attached falsifier.", "review",
        )

    tdd.run_execfind_contract("inline_fixture_artifact_ref", check)


def test_brokered_text_only():
    def check():
        tdd.require_attr(pi, "FindingFalsifier")
        entry = _golden()["attachment"]["falsifiers"][0]
        artifact = _falsifier_text(entry)
        for harness in ("claude", "gemini"):
            assert pi.sandbox_usable_by(harness, brokered=True) is False
            prompt = pi._render_broker_inline_prompt(
                artifact, "Treat the falsifier as a test proposal, not a tool call.",
                "review", staged_tree=None,
            )
            assert entry["diff"] in prompt
            assert "Do not use or request tools" in prompt
            assert "UNTRUSTED-REVIEW-BUNDLE sha256=" in prompt

    tdd.run_execfind_contract("brokered_text_only", check)


def test_prompt_over_cap_refused():
    def check():
        tdd.require_attr(pi, "FindingFalsifier")
        entry = _golden()["attachment"]["falsifiers"][0]
        artifact = _falsifier_text(entry) + ("x" * pi._BROKER_SEALED_PROMPT_MAX_BYTES)
        with pytest.raises(ValueError, match="sealed transport bound"):
            pi._render_broker_inline_prompt(artifact, "Review the artifact.", "review")

    tdd.run_execfind_contract("prompt_over_cap_refused", check)
