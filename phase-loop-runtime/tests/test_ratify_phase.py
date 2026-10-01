"""EC-RATIFY-1/-2/-4/-5 falsifiers, with legacy and receipt-soundness controls."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import inspect
from types import SimpleNamespace
import tempfile
from xml.etree import ElementTree

import pytest

import ratify_content_tdd_adapter as tdd
from phase_loop_runtime import gate_posture, governed_review as gr, panel_invoker as pi
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD, DEFAULT_SEATS
from phase_loop_runtime.falsifier import FalsifierRunResult
from phase_loop_runtime.ratification_policy import RatificationPolicy
from test_execfind_falsifier import _falsifier_text, _golden, _source_repo
from test_president_wiring import _runner_fixture
from test_presroute_cli import _artifact, _stub_mint

ROOT = Path(__file__).resolve().parents[2]
CLASSES = ("round_local", "contract_changing", "roadmap_changing", "release_rule")


def _ruling(ruling_class="round_local", *, disposition="DEFERRED"):
    return pi.PresidentRuling(
        model="claude-opus-5-5",
        text=f"FINDING F001: {disposition} {ruling_class} — retained concern\nFORCING DECISION: PROCEED",
        substantive_rounds=1, format_reasks=0,
    )


def _gate(tmp_path, monkeypatch, president=None, *, with_seam=True, foreign=False,
          verdicts=("AGREE",) * 4):
    repo, head = _source_repo(tmp_path)
    entry = _golden()["attachment"]["falsifiers"][0]
    body = _falsifier_text(entry).removesuffix("DISAGREE\n") + "AGREE\n"
    board = DEFAULT_BOARD
    legs = tuple(pi.PanelLegResult(seat.harness, "OK",
                                  body.removesuffix("AGREE\n") + verdicts[i] + "\n" if i < 2 else verdicts[i],
                                  seat_key=seat.seat_key)
                 for i, seat in enumerate(board.seats))
    panel = pi.PanelResult(legs)
    if foreign:
        pi.attach_finding_falsifiers(legs[0], pi.parse_finding_falsifiers(body))
    runs = []

    def measured(**kwargs):
        # Hermetic seam: real gate validates these records; no provider is launched.
        item = kwargs["falsifier"]
        outcome = "red_on_head" if not runs else "green_on_head"
        record = {**_golden()["record"], "reviewed_sha": head,
                  "seat_key": kwargs["seat_key"], "outcome": outcome,
                  "red_output_digest": _golden()["record"]["red_output_digest"] if outcome == "red_on_head" else None,
                  "nodeid": item.expected_nodeid,
                  "diff_digest": hashlib.sha256(item.diff.encode()).hexdigest()}
        runs.append(record)
        return FalsifierRunResult(outcome=outcome, nodeid=item.expected_nodeid,
            red_output_digest=record["red_output_digest"], diff_digest=record["diff_digest"],
            junit_path=None, detail=None, record=record)

    monkeypatch.setattr(gr, "run_finding_falsifier", measured)
    # The injected board returns fixture legs and launches no provider. Probe
    # fixtures must not depend on a live agy image or claim its qualification.
    monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", lambda *_args: None)
    kwargs = {}
    if with_seam:
        kwargs = {"president_invoke": president, "stream_dir": tmp_path / "stream"}
    gate = gr.governed_board_gate(
        artifact="Exact candidate", author_executor="train-coordinator", run_mode="governed",
        reviewed_sha=head, canonical_repo_authority=repo, compose=lambda: board,
        invoke=lambda *_a, **_k: panel, monitoring_policy="heartbeat_only", **kwargs,
    )
    return gate, runs, head


def _defer_all(_model, prompt, *, ruling_class="round_local"):
    ids = re.findall(r"(?m)^(F[0-9]+):", prompt)
    assert ids, "president received no residuals"
    return {"status": "ok", "text": "\n".join(
        f"FINDING {fid}: DEFERRED {ruling_class} — author retains the concern" for fid in ids
    ) + "\nFORCING DECISION: PROCEED"}


def test_receipt_partition(tmp_path, monkeypatch):
    def check():
        seen = []
        def president(model, prompt):
            seen.append(prompt)
            return _defer_all(model, prompt)
        gate, runs, head = _gate(tmp_path, monkeypatch, president)
        assert len(runs) == 2 and {r["outcome"] for r in runs} == {"red_on_head", "green_on_head"}
        assert len(seen) == 1 and gate.promoted
        prompt = seen[0]
        for record in runs:
            digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            assert record["seat_key"] in prompt and digest in prompt
            assert record["outcome"] in prompt
        assert len(re.findall(r"(?m)^F[0-9]+:", prompt)) >= 2
        assert not any(f.code == "finding_bound" for f in gate.findings)
        saved = json.loads((tmp_path / "stream" / "president.ruling.json").read_text())
        assert saved["schema"] == "president.ruling.v1"
        assert saved["authorization_identity"] == "public_board_president.v1"
        assert head in json.dumps(asdict(gate))
    tdd.run_contract("receipt_partition", "resolution", check)


def test_receipt_partition_scope_item_requires_ruling():
    def check():
        findings = ("F001: receipt residual", "F002: scope item on unchanged code")
        text = "FINDING F001: DEFERRED round_local — retained\nFORCING DECISION: PROCEED"
        assert not pi._valid_president_grammar(text, findings)
        text = text.replace("\nFORCING", "\nFINDING F002: DEFERRED round_local — tracked follow-up\nFORCING")
        assert pi._valid_president_grammar(text, findings)
    tdd.run_contract("receipt_partition_scope_item_requires_ruling", "resolution", check)


def test_receipt_partition_changing_without_row(tmp_path, monkeypatch):
    def check():
        for ruling_class in CLASSES[1:]:
            folder = tmp_path / ruling_class; folder.mkdir()
            seen = []
            def president(model, prompt):
                seen.append(prompt)
                return _defer_all(model, prompt, ruling_class=ruling_class)
            gate, runs, _head = _gate(folder, monkeypatch, president)
            assert len(runs) == 2 and len(seen) == 1, "post-receipt president seam not entered"
            assert not gate.promoted, "changing DEFERRED ruling has no checked ledger row"
            saved = json.loads((folder / "stream" / "president.ruling.json").read_text())
            assert saved["schema"] == "president.ruling.v1" and ruling_class in json.dumps(saved)
    tdd.run_contract("receipt_partition_changing_without_row", "resolution", check)


def test_receipt_partition_nonunanimous(tmp_path, monkeypatch):
    def check():
        for verdict in ("PARTIALLY AGREE", "DISAGREE"):
            folder = tmp_path / verdict; folder.mkdir()
            seen = []
            def president(model, prompt):
                seen.append(prompt)
                return _defer_all(model, prompt)
            gate, runs, _head = _gate(folder, monkeypatch, president,
                                     verdicts=("AGREE", "AGREE", "AGREE", verdict))
            assert len(runs) == 2 and len(seen) == 1, "post-receipt president seam not entered"
            assert not gate.promoted, "DEFERRED ruling erased a non-unanimous board"
            saved = json.loads((folder / "stream" / "president.ruling.json").read_text())
            assert saved["schema"] == "president.ruling.v1"
    tdd.run_contract("receipt_partition_nonunanimous", "resolution", check)


def test_receipt_partition_bound_findings_excluded():
    def check():
        from phase_loop_runtime.closeout_validators import ReviewFinding
        render = tdd.require_attr(pi, "president_residual_findings")
        findings = (
            ReviewFinding(code="finding_bound", severity="warn", reason="legacy bound F999", body="BOUND_ONLY_TEXT", reviewed_sha="a" * 40),
            ReviewFinding(code="finding_prose", severity="warn", reason="scope residual", body="SCOPE_ITEM_TEXT", reviewed_sha="a" * 40),
        )
        residual = render(findings, reviewed_sha="a" * 40)
        prompt = pi._president_prompt(residual)
        assert "BOUND_ONLY_TEXT" not in prompt and "SCOPE_ITEM_TEXT" in prompt
        ids = [line.split(":", 1)[0] for line in residual]
        ruling = "\n".join(f"FINDING {fid}: DEFERRED round_local — retained" for fid in ids)
        ruling += "\nFORCING DECISION: PROCEED"
        assert pi._valid_president_grammar(ruling, residual)
        assert not pi._valid_president_grammar(
            "FINDING F999: DEFERRED round_local — waive bound finding\n" + ruling, residual)
    tdd.run_contract("receipt_partition_bound_findings_excluded", "resolution", check)


def test_receipt_partition_missing_or_stale_ruling(tmp_path, monkeypatch):
    def check():
        gate, runs, _head = _gate(tmp_path, monkeypatch, with_seam=False)
        assert runs and not gate.promoted and any(f.code == "finding_receipt" for f in gate.findings)
        other = tmp_path / "stale"; other.mkdir()
        def stale(_model, _prompt):
            return {"status": "ok", "text": "FINDING FOREIGN: DEFERRED round_local — another tree\nFORCING DECISION: PROCEED"}
        gate, _runs, _head = _gate(other, monkeypatch, stale)
        assert not gate.promoted
    tdd.run_contract("receipt_partition_missing_or_stale_ruling", "resolution", check)


def test_receipt_partition_native_deferral(tmp_path, monkeypatch):
    def check():
        calls = []
        def deferred(model, prompt):
            calls.append((model, prompt))
            return {"status": pi.PRESIDENT_NATIVE_FILL_DEFERRED_STATUS, "rung": model, "prompt": prompt}
        gate, _runs, _head = _gate(tmp_path, monkeypatch, deferred)
        assert calls and not gate.promoted
        assert "native" in json.dumps(asdict(gate)).lower()
        assert all(getattr(f, "human_required", False) is not True for f in gate.findings)
    tdd.run_contract("receipt_partition_native_deferral", "resolution", check)


def test_receipt_partition_foreign_attachment(tmp_path, monkeypatch):
    def check():
        calls = []
        gate, runs, _head = _gate(tmp_path, monkeypatch, lambda *a: calls.append(a), foreign=True)
        assert not gate.promoted and gate.reason == "foreign_falsifier_attachment"
        assert not runs and not calls
    tdd.run_contract("receipt_partition_foreign_attachment", "resolution", check)


def test_ruling_classes():
    def check():
        findings = ("F001: residual",)
        for ruling_class in CLASSES:
            ruling = _ruling(ruling_class)
            assert pi._valid_president_grammar(ruling.text, findings)
            parsed = pi.president_finding_rulings(ruling)
            assert len(parsed) == 1 and parsed[0].ruling_class == ruling_class
        for text in (
            _ruling("invented").text,
            _ruling().text.replace("F001", "F002"),
            _ruling().text.replace("\nFORCING", "\nFINDING F001: DEFERRED round_local — duplicate\nFORCING"),
            _ruling().text + "\ntrailing prose",
            "FINDING F001: DEFERRED round_local — residual\nFORCING DECISION:",
        ):
            assert not pi._valid_president_grammar(text, findings)
        assert pi.president_blocks_landing(_ruling(disposition="BLOCKING"))
    tdd.run_contract("ruling_classes", "resolution", check)


def test_ruling_classes_legacy_compatibility():
    def check():
        legacy = pi.PresidentRuling("claude-opus-5-5", "FINDING F001: DEFERRED — legacy\nFORCING DECISION: PROCEED", 1, 0)
        assert pi._valid_president_grammar(legacy.text, ("F001: residual",))
        assert pi.president_finding_rulings(legacy)[0].ruling_class == "round_local"
        assert pi.PresidentFindingRuling("F001", "DEFERRED", "old constructor").ruling_class == "round_local"
    tdd.run_contract("ruling_classes_legacy_compatibility", "resolution", check)


def test_ruling_classes_changing_without_row():
    def check():
        for ruling_class in CLASSES[1:]:
            assert pi.president_blocks_landing(_ruling(ruling_class)), "typed DEFERRED cannot waive a missing checked row"
    tdd.run_contract("ruling_classes_changing_without_row", "resolution", check)


def _bindings():
    return {"reviewed_sha": "a" * 40, "instruction_digest": "b" * 64,
            "board_digest": "c" * 64, "findings_digest": "d" * 64,
            "authorization_identity": "public_board_president.v1"}


def _bind(ruling, verdicts=("AGREE",) * 4, *, binding=None):
    binder = tdd.require_attr(pi, "bind_ratify_resolution")
    return binder(ruling, required_seat_verdicts=verdicts,
                  binding=binding or _bindings(), expected_binding=_bindings())


def test_ruling_classes_binding():
    def check():
        assert not pi.president_blocks_landing(_bind(_ruling()))
        for key in _bindings():
            changed = {**_bindings(), key: "foreign"}
            assert pi.president_blocks_landing(_bind(_ruling(), binding=changed)), key
        for key, value in _bindings().items():
            if key == "authorization_identity":
                continue
            changed = {**_bindings(), key: "e" * len(value)}
            assert pi.president_blocks_landing(_bind(_ruling(), binding=changed)), f"well-formed stale {key}"
        assert pi.president_blocks_landing(_ruling("contract_changing"))
    tdd.run_contract("ruling_classes_binding", "resolution", check)


def test_ruling_classes_real_consumers(tmp_path, monkeypatch, capsys):
    def check():
        from phase_loop_runtime import runner, cli, legible_evidence
        repo, run_dir, bundle = _runner_fixture(tmp_path)
        entered = []
        predicate = pi.president_blocks_landing
        def observed(ruling):
            entered.append(ruling)
            return predicate(ruling)
        monkeypatch.setattr(pi, "president_blocks_landing", observed)
        rulings = (
            _ruling("contract_changing"),
            _bind(_ruling(), ("AGREE", "AGREE", "AGREE", "PARTIALLY AGREE")),
        )
        for ruling in rulings:
            legs = tuple(pi.PanelLegResult(seat.harness, "OK", "AGREE", seat_key=seat.seat_key)
                         for seat in DEFAULT_SEATS)
            result = pi.PanelResult(legs, president=ruling, president_findings=("F001: residual",))
            monkeypatch.setattr(pi, "invoke_board", lambda *_a, **_k: result)
            before = len(entered)
            with pytest.raises(legible_evidence.LegibleProcessBootstrapError):
                runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
            assert len(entered) == before + 1, "runner held before entering the named predicate"
            assert not (run_dir / "implementation-panel.json").exists()
            _stub_mint(monkeypatch, tmp_path)
            before = len(entered)
            assert cli.main(["advisor-board", str(_artifact(tmp_path)), "--landing-tier", "production_code"]) != 0
            assert len(entered) == before + 1, "CLI held before entering the named predicate"
            capsys.readouterr()
    tdd.run_contract("ruling_classes_real_consumers", "resolution", check)


def _escalate(tier, ruling_class, *, unanimous=True, exhausted=False, run_mode="unattended"):
    module = tdd.require_module("phase_loop_runtime.ratification_policy")
    resolve = tdd.require_attr(module, "resolve_ruling_escalation")
    policy = RatificationPolicy(3, 3, "majority", "proceed_degraded", human_tier=tier)
    return resolve(policy=policy, ruling=_ruling(ruling_class), unanimous=unanimous,
                   ladder_exhausted=exhausted, run_mode=run_mode)


def test_human_tiers(monkeypatch):
    def check():
        monkeypatch.setattr("builtins.input", lambda *a, **k: (_ for _ in ()).throw(AssertionError("synchronous wait")))
        for tier in ("never", "contract_changing", "always"):
            for ruling_class in CLASSES:
                for mode in ("attended", "unattended"):
                    decision = _escalate(tier, ruling_class, run_mode=mode)
                    hold = tier == "always" or (tier == "contract_changing" and ruling_class != "round_local")
                    assert decision.blocks is hold
                    assert decision.human_required is (hold and mode == "attended")
                    if hold:
                        assert decision.ruling == _ruling(ruling_class)
    tdd.run_contract("human_tiers", "resolution", check)


def test_human_tiers_universal_triggers():
    def check():
        for tier in ("never", "contract_changing", "always"):
            for unanimous, exhausted in ((False, False), (True, True), (False, True)):
                for mode in ("attended", "unattended"):
                    result = _escalate(tier, "round_local", unanimous=unanimous, exhausted=exhausted, run_mode=mode)
                    assert result.blocks and result.human_required is (mode == "attended")
        # A PARTIALLY AGREE/absent seat must not inherit the old consensus helper's majority.
        ruling = _ruling()
        for verdict in ("PARTIALLY AGREE", None):
            bound = _bind(ruling, ("AGREE", "AGREE", "AGREE", verdict))
            assert pi.president_blocks_landing(bound)
    tdd.run_contract("human_tiers_universal_triggers", "resolution", check)


def test_human_tiers_invalid_overrides():
    def check():
        default = gate_posture.resolve_ratification_policy("pre-merge-CR")
        assert default.human_tier == "never"
        signature = inspect.signature(RatificationPolicy)
        assert signature.parameters["human_tier"].kind == inspect.Parameter.KEYWORD_ONLY
        if "required_prover" in signature.parameters:
            assert RatificationPolicy(3, 3, "majority", "escalate", False).required_prover is False
        assert list(asdict(RatificationPolicy(3, 3, "majority", "escalate")))[:4] == [
            "required_vendors", "required_lens_coverage", "required_consensus", "on_shortfall"]
        for override in (
            {"human_tier": "unknown"}, {"human_tier": None}, {"human_tier": []},
            {"human_tier": "always", "on_shortfall": "unknown"},
            {"human_tier": "always", "required_vendors": "invalid"},
            {"human_tier": "always", "required_lens_coverage": 0},
            {"human_tier": "always", "required_consensus": "plurality"},
        ):
            manifest = {"ratification_policy_overrides": {"pre-merge-CR": override}}
            with pytest.raises(ValueError) as error:
                gate_posture.resolve_ratification_policy("pre-merge-CR", manifest=manifest)
            assert getattr(error.value, "code", None) == "ratification_policy_invalid"
            assert getattr(error.value, "human_required", None) is False
    tdd.run_contract("human_tiers_invalid_overrides", "resolution", check)


def test_skill_reconciliation():
    def check():
        # Code activation, not a substring in a skill, controls this falsifier.
        groups = (
            ("advisory", "receipt"), ("president", "residual"),
            ("ledger", "changing"), ("guard", "author"),
        )
        from phase_loop_runtime.skill_install import install_skills
        def verify_steps(text):
            lower = text.lower()
            cursor = 0
            for group in groups:
                left, right = group
                pair = rf"\b{left}\b.{{0,180}}?\b{right}\b|\b{right}\b.{{0,180}}?\b{left}\b"
                match = re.search(pair, lower[cursor:], re.S)
                assert match, f"missing or unordered reconciliation step: {group}"
                cursor += match.end()
        for harness in ("codex", "claude", "gemini", "opencode"):
            for skill in ("plan-phase", "execute-phase"):
                canonical = ROOT / "skills-src" / harness / f"{harness}-{skill}" / "SKILL.md"
                texts = [canonical.read_text(encoding="utf-8")]
                packaged = ROOT / "phase-loop-runtime/src/phase_loop_runtime/skills_bundle" / f"{harness}-{skill}" / "SKILL.md"
                texts.append(packaged.read_text(encoding="utf-8"))
                for text in texts:
                    verify_steps(text)
                # Installed delivery is an independent boundary, not source-only proof.
                with tempfile.TemporaryDirectory(prefix="ratify-skills-") as temp:
                    dest = Path(temp)
                    install_skills(harness=harness, source=ROOT / "phase-loop-skills",
                                   destination=dest, mode="copy", apply=True, expand_body=True)
                    installed = (dest / f"{harness}-{skill}" / "SKILL.md").read_text(encoding="utf-8")
                    verify_steps(installed)
                    for group in groups:
                        mutant = re.sub(r"\b" + group[0] + r"\b", "removed_step", installed, flags=re.I)
                        with pytest.raises(AssertionError):
                            verify_steps(mutant)
    tdd.run_contract("skill_reconciliation", "resolution", check)


def test_legacy_grammar_control():
    text = "FINDING F001: DEFERRED — legacy\nFORCING DECISION: PROCEED"
    assert pi._valid_president_grammar(text, ("F001: legacy",))
    assert not pi._valid_president_grammar(text, ("F001: legacy", "F002: omitted"))


def test_old_policy_constructor_control():
    policy = RatificationPolicy(3, 3, "majority", "escalate")
    assert policy.required_vendors == 3 and policy.on_shortfall == "escalate"
    malformed = {"ratification_policy_overrides": {"pre-merge-CR": {"on_shortfall": "unknown"}}}
    assert gate_posture.resolve_ratification_policy("pre-merge-CR", manifest=malformed) == gate_posture.resolve_ratification_policy("pre-merge-CR")


def test_receipt_binding_control(tmp_path, monkeypatch):
    gate, runs, _head = _gate(tmp_path, monkeypatch, with_seam=False)
    assert len(runs) == 2 and {r["outcome"] for r in runs} == {"red_on_head", "green_on_head"}
    receipts = [f for f in gate.findings if f.code == "finding_receipt"]
    assert len(receipts) == 2 and all("record_digest=unresolved" not in f.reason for f in receipts)
    assert not gate.promoted  # The no-seam compatibility hold remains.


def test_landed_guard_marker_removal(monkeypatch):
    import test_ratify_landed as landed
    monkeypatch.delenv("PHASE_LOOP_TDD_EXPECT_RATIFY", raising=False)
    monkeypatch.delenv("PHASE_LOOP_TDD_REQUIRE_RATIFY_GREEN", raising=False)
    monkeypatch.setattr(landed, "_ratify_completed", lambda: True)
    monkeypatch.setattr(tdd, "capability", lambda lane: (_ for _ in ()).throw(tdd.MissingCapability("deleted marker")))
    with pytest.raises(tdd.MissingCapability, match="deleted marker"):
        landed.test_no_ratify_contract_skips_as_unimplemented()


def test_guard_proof_fixture_control(tmp_path):
    from test_ruling_ledger import _repo, _proof
    from phase_loop_runtime.verification_evidence import validate_verification_artifact
    repo, _head = _repo(tmp_path)
    proof = _proof(repo)["test_guard.py::test_guard"]
    assert validate_verification_artifact(Path(proof["verification_artifact_path"])).ok
    cases = list(ElementTree.parse(proof["junit_path"]).getroot().iter("testcase"))
    assert len(cases) == 1 and cases[0].get("name") == "test_guard"
    assert cases[0].find("failure") is None and cases[0].find("skipped") is None


def test_governed_gate_bypass_control(tmp_path, monkeypatch):
    real_gate = gr.governed_board_gate
    def bypass(**kwargs):
        president = kwargs.pop("president_invoke", None)
        stream = kwargs.pop("stream_dir", None)
        gate = real_gate(**kwargs)
        if president is None:
            return gate
        prompt = "\n".join(
            f"F{i:03}: {finding.reason}\n{finding.body or ''}"
            for i, finding in enumerate(gate.findings, 1) if finding.code == "finding_receipt")
        text = president("claude-opus-5-5", prompt)["text"]
        stream.mkdir(parents=True, exist_ok=True)
        (stream / "president.ruling.json").write_text(json.dumps({
            "schema": "president.ruling.v1", "authorization_identity": "public_board_president.v1", "text": text}))
        return replace(gate, promoted=True)  # Mutation: bypass ledger and unanimity.
    with monkeypatch.context() as mutation:
        mutation.delenv("PHASE_LOOP_TDD_EXPECT_RATIFY", raising=False)
        mutation.setattr(tdd, "capability", lambda lane: object())
        mutation.setattr(gr, "governed_board_gate", bypass)
        positive = tmp_path / "positive"; positive.mkdir()
        test_receipt_partition(positive, mutation)
        for case in (test_receipt_partition_changing_without_row, test_receipt_partition_nonunanimous):
            folder = tmp_path / case.__name__; folder.mkdir()
            with pytest.raises(AssertionError, match="changing DEFERRED|non-unanimous board"):
                case(folder, mutation)
    assert gr.governed_board_gate is real_gate


def test_shape_only_binding_control(monkeypatch):
    real_predicate = pi.president_blocks_landing
    def shape_only(ruling, *, required_seat_verdicts, binding, expected_binding):
        widths = {"reviewed_sha": 40, "instruction_digest": 64, "board_digest": 64, "findings_digest": 64}
        valid = all(re.fullmatch(r"[0-9a-f]{%d}" % width, binding.get(key, "")) for key, width in widths.items())
        valid = valid and binding.get("authorization_identity") == "public_board_president.v1"
        return SimpleNamespace(held=not valid or any(v != "AGREE" for v in required_seat_verdicts))
    def blocks(ruling):
        if hasattr(ruling, "held"):
            return ruling.held
        return "contract_changing" in ruling.text or ": BLOCKING" in ruling.text
    with monkeypatch.context() as mutation:
        mutation.delenv("PHASE_LOOP_TDD_EXPECT_RATIFY", raising=False)
        mutation.setattr(tdd, "capability", lambda lane: object())
        mutation.setattr(pi, "bind_ratify_resolution", shape_only, raising=False)
        mutation.setattr(pi, "president_blocks_landing", blocks)
        assert not blocks(_bind(_ruling()))
        with pytest.raises(AssertionError, match="well-formed stale"):
            test_ruling_classes_binding()
    assert pi.president_blocks_landing is real_predicate


def test_unknown_capability_strict_failure(monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_TDD_EXPECT_RATIFY", raising=False)
    monkeypatch.setenv("PHASE_LOOP_TDD_REQUIRE_RATIFY_RESOLUTION_GREEN", "1")
    monkeypatch.setattr(tdd, "capability", lambda lane: (_ for _ in ()).throw(tdd.MissingCapability("absent")))
    with pytest.raises(tdd.MissingCapability):
        tdd.run_contract("ruling_classes", "resolution", lambda: None)


def test_unexpected_pass_refused(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_TDD_EXPECT_RATIFY", "1")
    monkeypatch.setattr(tdd, "capability", lambda lane: SimpleNamespace())
    with pytest.raises(AssertionError, match="RATIFY_RECORD_UNSOUND"):
        tdd.run_contract("ruling_classes", "resolution", lambda: None)


def test_unrelated_exception_propagates(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_TDD_EXPECT_RATIFY", "1")
    monkeypatch.setattr(tdd, "capability", lambda lane: SimpleNamespace())
    for exception in (RuntimeError("unrelated"), AssertionError("real assertion")):
        with pytest.raises(type(exception), match=str(exception)):
            tdd.run_contract("ruling_classes", "resolution", lambda: (_ for _ in ()).throw(exception))


def test_importerror_not_capability_absence(monkeypatch):
    def missing_dependency(name):
        raise ModuleNotFoundError("dependency absent", name="different_dependency")
    monkeypatch.setattr(tdd.importlib, "import_module", missing_dependency)
    with pytest.raises(ModuleNotFoundError):
        tdd.require_module("phase_loop_runtime.ruling_ledger")


def _inventory():
    return SimpleNamespace(test_files=[(path, "a" * 64) for path in sorted(tdd.FROZEN_FILES)],
                           red_nodeids=sorted(tdd.EXPECTED_RED_NODES | tdd.EXPECTED_GREEN_NODES))


def _red_log():
    return "\n".join(
        [f"AssertionError: {tdd.RED_ANCHOR_MARKER} RATIFY_RED::{case}" for case in sorted(tdd.EXPECTED_MARKERS)]
        + [f"FAILED {node}" for node in sorted(tdd.EXPECTED_RED_NODES)]
        + [f"PASSED {node}" for node in sorted(tdd.EXPECTED_GREEN_NODES)]
    )


def test_red_inventory_exact():
    receipt = _inventory()
    assert tdd.scan_inventory(receipt) is None
    receipt.red_nodeids.pop()
    assert tdd.scan_inventory(receipt)
    receipt = _inventory(); receipt.test_files.pop()
    assert tdd.scan_inventory(receipt)


def test_red_marker_exact():
    log = _red_log()
    assert tdd.scan_red_output(log) is None
    assert tdd.scan_red_output(log.replace("RATIFY_RED::ruling_classes\n", "RATIFY_RED::ruling_classes_extra\n"))
    assert tdd.scan_red_output(log + f"\n{tdd.RED_ANCHOR_MARKER} RATIFY_RED::ruling_classes")
    assert tdd.scan_red_output(log.replace("FAILED ", "NOTFAILED ", 1))


def test_red_skips_refused():
    assert tdd.scan_red_output(_red_log() + "\nSKIPPED one missing node")


def test_red_xpass_refused():
    assert tdd.scan_red_output(_red_log() + "\nXPASS unexpected pass")


def test_landing_junit_zero_skips(tmp_path):
    root = ElementTree.Element("testsuite")
    for node in sorted(tdd.EXPECTED_RED_NODES | tdd.EXPECTED_GREEN_NODES):
        file, name = node.split("::")
        ElementTree.SubElement(root, "testcase", classname=Path(file).stem, name=name)
    path = tmp_path / "landing.xml"
    ElementTree.ElementTree(root).write(path)
    assert tdd.scan_landing_junit(path) is None
    ElementTree.SubElement(root[0], "skipped")
    ElementTree.ElementTree(root).write(path)
    assert tdd.scan_landing_junit(path)
    root.remove(root[0]); ElementTree.ElementTree(root).write(path)
    assert tdd.scan_landing_junit(path)


def test_touch_shape_owner_serialization(tmp_path):
    from test_ruling_ledger import _repo, _commit
    repo, _head = _repo(tmp_path)
    source = repo / "shared.py"
    source.write_text("def president_blocks_landing():\n    return False\n\ndef launch_provider():\n    return 1\n")
    before = _commit(repo, "shared baseline")
    seams = {"shared.py": ("president_blocks_landing",)}
    source.write_text(source.read_text().replace("return False", "return True"))
    good = _commit(repo, "named seam")
    assert tdd.check_touch_shape(repo, before, good, seams, ()) is None
    assert tdd.check_touch_shape(repo, before, good, seams, ("agent-harness#1166",))
    source.write_text(source.read_text().replace("return 1", "return 2"))
    bad = _commit(repo, "foreign rewrite")
    assert tdd.check_touch_shape(repo, before, bad, seams, ())


def test_rejected_recording_no_receipt(tmp_path, monkeypatch):
    def unsound(**kwargs):
        staged = kwargs["out"]
        staged.write_text("{}")
        (staged.parent / "red.log").write_text(_red_log() + "\nXPASS unexpected pass")
        (staged.parent / "empty.log").write_text("")
        return SimpleNamespace(**vars(_inventory()), red_stdout_path="red.log", red_stderr_path="empty.log")
    monkeypatch.setattr(tdd, "record_content_tdd_receipt", unsound)
    out = tmp_path / "receipt.json"
    assert tdd.main(["record-red", "--repo", str(tmp_path), "--receipt", str(out)]) == 1
    assert not out.exists() and not (tmp_path / "red.log").exists()


def test_verify_rescans_red_log(tmp_path, monkeypatch):
    receipt = SimpleNamespace(**vars(_inventory()), red_stdout_path="red.log", red_stderr_path="empty.log")
    monkeypatch.setattr(tdd, "verify_content_tdd_receipt", lambda **kwargs: receipt)
    (tmp_path / "red.log").write_text(_red_log().replace("FAILED ", "PASSED ", 1))
    (tmp_path / "empty.log").write_text("")
    with pytest.raises(ValueError, match="node inventory"):
        tdd.verify(tmp_path, "HEAD", tmp_path / "receipt.json")
