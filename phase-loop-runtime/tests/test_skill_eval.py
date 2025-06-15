"""Falsifying offline protocol tests. No provider or private reflection reads."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from phase_loop_runtime import skill_eval as ev


PILOT = Path(__file__).parent / "fixtures" / "skill_eval" / "pilot.json"


@pytest.fixture
def experiment(tmp_path):
    root = tmp_path / "experiment"
    frozen = ev.prepare(PILOT, root)
    return root, frozen, ev.Spec.model_validate(frozen["spec"])


def seal(root, frozen, spec, trial, *, exposed=True, reads=True, valid=True, text="Evidence plan."):
    directory = root / "trials" / trial["id"]
    bound = ev.binding(frozen, spec, trial)
    if not (directory / "started.json").exists():
        ev.write_new(directory / "started.json", bound)
    joined = {**bound, "output_digest": ev.digest(text.encode())}
    access = {"binding": joined, "errors": [], "events": {
        name: {"open": True, "access": exposed if name == ev.GUIDE else reads}
        for name in ev.files_for(frozen, spec, trial)}}
    launch = {"binding": joined, "returncode": 0, "probe": "passed", "stream_valid": True,
              "usage": None, "elapsed_seconds": .1, "transcript_digest": ev.digest(b"stream")}
    (directory / "transcript.txt").write_text("stream")
    ev.write_new(directory / "access.json", access)
    ev.write_new(directory / "launch.json", launch)
    ev.write_new(directory / "terminal.json", {
        "binding": bound, "output": text, "output_digest": joined["output_digest"],
        "status": "completed" if valid else "invalid", "reason": None,
        "launch_digest": ev.digest(launch), "access_digest": ev.digest(access)})


def scored_packet(root, out, *, calibration=False, choose=None, scorer="blind-human"):
    packet = ev.packet(root, out, calibration)
    scores = ev.load(out / "scores.json")
    scores["scorer_id"] = scorer
    scores["no_prior_gold_exposure"] = calibration
    spec = ev.open_experiment(root)[1]
    annotations = {g.text: g.annotations for g in spec.gold}
    for row, score in zip(packet["outputs"], scores["scores"]):
        values = annotations[row["plan"]] if calibration else {
            key: (choose(row["id"], key) if choose else True) for key in row["rubric"]}
        score["items"] = {key: {"pass": values[key], "quote": row["plan"]} for key in row["rubric"]}
    path = out / "sealed.json"
    ev.write_new(path, scores)
    return packet, scores, path


def qualify(root, tmp_path, *, scorer="blind-human"):
    _, _, path = scored_packet(root, tmp_path / "gold", calibration=True, scorer=scorer)
    assert ev.reduce(root, path, tmp_path / "gold-result", True)["calibration_passed"]


def rewrite(path, value):
    path.write_bytes(ev.canonical(value))


def test_roundtrip_independent_variants_balanced_schedule(experiment):
    root, frozen, spec = experiment
    assert ev.open_experiment(root)[0] == frozen
    assert len(frozen["schedule"]) == 48
    for comparison in spec.comparisons:
        arms = frozen["arms"][comparison.id]
        assert arms["bytes"][arms["baseline"]] == spec.baseline
        expected = spec.baseline.replace(ev.ANCHOR, ev.CANDIDATES[comparison.id])
        assert arms["bytes"][arms["treatment"]] == expected
        other = "oracle" if comparison.id == "layer" else "layer"
        assert ev.CANDIDATES[other] not in expected
        starts = [t["arm"] for t in frozen["schedule"] if t["comparison"] == comparison.id][::2]
        assert starts.count(arms["baseline"]) == starts.count(arms["treatment"]) == 6
    with pytest.raises(FileExistsError):
        ev.prepare(PILOT, root)


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(unknown=True),
    lambda s: s.update(repetitions=4),
    lambda s: s.update(version=True),
    lambda s: s.update(profile="review"),
    lambda s: s.update(effort=""),
    lambda s: s.update(baseline="missing anchor"),
    lambda s: s["comparisons"][0]["edit"].update(new="unreviewed wording"),
    lambda s: s["comparisons"][0]["cases"][0].update(id=s["comparisons"][0]["cases"][1]["id"]),
    lambda s: s["comparisons"][0]["cases"][0].update(required=["missing"]),
    lambda s: s["comparisons"][0]["cases"][0]["files"].update({"../escape": "x"}),
    lambda s: s["comparisons"][0]["cases"][0]["files"].update({"/absolute": "x"}),
    lambda s: s["comparisons"][0]["cases"][0]["files"].update({".git/config": "x"}),
    lambda s: s["comparisons"][0]["cases"][0]["files"].update({"a": "x", "a/b": "x"}),
    lambda s: s["gold"][0]["annotations"].update(r1=1),
    lambda s: s["gold"][0]["citations"].update(r1="absent quote"),
    lambda s: s["executable"].update(diagnostic_allowlist=["ignore everything"]),
    lambda s: s.update(decision={"target_wins": 0}),
])
def test_invalid_specs(mutate):
    value = ev.load(PILOT)
    mutate(value)
    with pytest.raises(ValueError):
        ev.Spec.model_validate(value)


def test_input_links_and_duplicate_keys_refused(tmp_path):
    link = tmp_path / "linked"
    link.symlink_to(PILOT)
    with pytest.raises(ValueError):
        ev.load(link)
    path = tmp_path / "duplicate.json"
    path.write_text('{"version":1,"version":2}')
    with pytest.raises(ValueError, match="duplicate"):
        ev.load(path)


def test_mutation_and_resealed_schedule_refused(experiment):
    root, frozen, spec = experiment
    frozen["spec"]["baseline"] += "mutated"
    rewrite(root / "frozen.json", frozen)
    with pytest.raises(ValueError, match="changed"):
        ev.open_experiment(root)
    frozen["spec"]["baseline"] = spec.baseline
    frozen["schedule"][1]["arm"] = frozen["schedule"][0]["arm"]
    frozen["digest"] = ev.digest({k: v for k, v in frozen.items() if k != "digest"})
    rewrite(root / "frozen.json", frozen)
    with pytest.raises(ValueError, match="pair"):
        ev.open_experiment(root)


def test_runtime_drift_refused(experiment, monkeypatch):
    root, _, _ = experiment
    monkeypatch.setattr(ev, "runtime_identity", lambda: {})
    with pytest.raises(ValueError, match="runtime"):
        ev.open_experiment(root)


def test_lock_refuses_concurrent_runner_before_claim(experiment, monkeypatch):
    root, _, _ = experiment
    from phase_loop_runtime import skill_eval_runner
    monkeypatch.setattr(skill_eval_runner, "run_trial", lambda *args: pytest.fail("unexpected launch"))
    with ev.experiment_lock(root):
        with pytest.raises(ValueError, match="locked"):
            ev.run(root)
    assert not (root / "trials").exists()


def test_no_retry_started_trial_and_48_budget(experiment, monkeypatch):
    root, frozen, spec = experiment
    from phase_loop_runtime import skill_eval_runner
    first = frozen["schedule"][0]
    ev.write_new(root / "trials" / first["id"] / "started.json", ev.binding(frozen, spec, first))
    calls = []
    def subject(root, frozen, spec, trial):
        calls.append(trial["id"])
        seal(root, frozen, spec, trial)
    monkeypatch.setattr(skill_eval_runner, "run_trial", subject)
    ev.run(root)
    ev.run(root)
    assert len(calls) == 47 and first["id"] not in calls
    assert not ev.evidence(root, frozen, spec, first)["valid"]


@pytest.mark.parametrize("swap", ["trial", "experiment", "files_digest", "guide_digest", "output_digest"])
def test_receipt_swaps_refused(experiment, swap):
    root, frozen, spec = experiment
    trial = frozen["schedule"][0]
    seal(root, frozen, spec, trial)
    path = root / "trials" / trial["id"] / "access.json"
    receipt = ev.load(path)
    receipt["binding"][swap] = "foreign"
    rewrite(path, receipt)
    assert not ev.evidence(root, frozen, spec, trial)["valid"]


@pytest.mark.parametrize("name", ["launch.json", "access.json", "terminal.json", "started.json", "transcript.txt"])
def test_missing_evidence_refused(experiment, name):
    root, frozen, spec = experiment
    trial = frozen["schedule"][0]
    seal(root, frozen, spec, trial)
    (root / "trials" / trial["id"] / name).unlink()
    assert not ev.evidence(root, frozen, spec, trial)["valid"]


def test_packet_blinding_and_field_allowlist(experiment, tmp_path):
    root, frozen, spec = experiment
    for trial in frozen["schedule"]:
        seal(root, frozen, spec, trial)
    packet = ev.packet(root, tmp_path / "packet")
    encoded = json.dumps(packet)
    for marker in [spec.model, spec.effort, str(root), ev.CANDIDATES["oracle"],
                   *[a for group in frozen["arms"].values() for a in group["bytes"]]]:
        assert marker not in encoded
    assert len(packet["outputs"]) == 48
    assert all(set(row) == {"id", "task", "facts", "plan", "rubric", "access"}
               for row in packet["outputs"])
    assert ev.packet(root, tmp_path / "second") == packet


@pytest.mark.parametrize("failure", ["missing", "duplicate", "unknown", "numeric", "citation", "foreign"])
def test_malformed_scores_refused(experiment, tmp_path, failure):
    root, frozen, spec = experiment
    seal(root, frozen, spec, frozen["schedule"][0])
    packet, scores, _ = scored_packet(root, tmp_path / "packet")
    if failure == "missing":
        scores["scores"].clear()
    elif failure == "duplicate":
        scores["scores"] *= 2
    elif failure == "unknown":
        scores["scores"][0]["id"] = "foreign"
    elif failure == "numeric":
        scores["scores"][0]["items"]["r1"]["pass"] = 1
    elif failure == "citation":
        scores["scores"][0]["items"]["r1"]["quote"] = "not in output"
    else:
        scores["packet_digest"] = "foreign"
    with pytest.raises(ValueError):
        ev.check_scores(scores, packet)


@pytest.mark.parametrize("scenario,expected", [
    ("three_wins", "promising"), ("two_wins", "no demonstrated improvement"),
    ("target_loss", "no demonstrated improvement"), ("control_loss", "no demonstrated improvement"),
    ("unexposed_baseline", "inconclusive"), ("control_all_fail", "inconclusive"),
    ("partial_scores", "no demonstrated improvement"), ("missing", "inconclusive"),
    ("unblinded", "inconclusive"), ("missing_access", "no demonstrated improvement"),
    ("no_calibration", "inconclusive"),
])
def test_exact_boolean_decision_boundaries(experiment, tmp_path, scenario, expected):
    root, frozen, spec = experiment
    if scenario != "no_calibration":
        qualify(root, tmp_path)
    by_output = {t["output_id"]: t for t in frozen["schedule"]}
    baseline_ids = set()
    for trial in frozen["schedule"]:
        baseline = trial["arm"] == frozen["arms"][trial["comparison"]]["baseline"]
        if baseline:
            baseline_ids.add(trial["output_id"])
        case = ev.case_for(spec, trial)
        if scenario == "missing" and baseline and case.kind == "target" and trial["repetition"] == 0:
            continue
        seal(root, frozen, spec, trial,
             exposed=not (scenario == "unexposed_baseline" and baseline and case.kind == "target"),
             reads=not (scenario == "missing_access" and not baseline),
             text=spec.model if scenario == "unblinded" and baseline else "Evidence plan.")
    def vote(output_id, key):
        trial = by_output[output_id]
        case = ev.case_for(spec, trial)
        baseline = output_id in baseline_ids
        if case.kind == "negative_control":
            return not (scenario == "control_all_fail" or scenario == "control_loss" and not baseline)
        if scenario == "partial_scores":
            return key != ("r1" if baseline else "r2")
        if scenario == "missing_access":
            return True
        if scenario == "target_loss" and trial["repetition"] == 2:
            return baseline
        if baseline:
            # One case supplies three wins; other target cases tie.
            first_target = next(c.id for group in spec.comparisons if group.id == trial["comparison"]
                                for c in group.cases if c.kind == "target")
            return not (case.id == first_target and
                        (scenario != "two_wins" or trial["repetition"] < 2))
        return True
    packet, scores, path = scored_packet(root, tmp_path / "packet", choose=vote)
    result = ev.reduce(root, path, tmp_path / "result")
    assert len(result["trials"]) == 48
    assert {c["status"] for c in result["comparisons"].values()} == {expected}
    if expected == "promising":
        assert all(c["pairs"]["target"] == {"wins": 3, "losses": 0, "ties": 6}
                   for c in result["comparisons"].values())
    if scenario == "missing":
        assert len(packet["outputs"]) < 48  # invalid no-output trials require no invented scores


@pytest.mark.parametrize("bad", ["wrong", "prior_exposure", "malformed"])
def test_calibration_is_one_shot_even_after_failure(experiment, tmp_path, bad):
    root, frozen, spec = experiment
    _, scores, path = scored_packet(root, tmp_path / "gold", calibration=True)
    if bad == "wrong":
        item = next(iter(scores["scores"][0]["items"].values()))
        item["pass"] = not item["pass"]
    elif bad == "prior_exposure":
        scores["no_prior_gold_exposure"] = False
    else:
        scores["scores"] = []
    rewrite(path, scores)
    if bad == "malformed":
        with pytest.raises(ValueError, match="invalid calibration scores"):
            ev.reduce(root, path, tmp_path / "result", True)
    else:
        assert ev.reduce(root, path, tmp_path / "result", True) == {"calibration_passed": False}
    assert ev.load(root / "calibration-receipt.json")["passed"] is False
    with pytest.raises(FileExistsError):
        ev.reduce(root, path, tmp_path / "retry", True)
    assert not ev.calibration_valid(root, frozen, spec, "blind-human")


def test_calibration_packet_has_no_annotations_and_started_attempt_cannot_retry(experiment, tmp_path):
    root, frozen, spec = experiment
    packet = ev.packet(root, tmp_path / "gold", True)
    assert len(packet["outputs"]) == 16
    assert "annotations" not in json.dumps(packet) and "citations" not in json.dumps(packet)
    ev.write_new(root / "calibration-started.json", {"experiment": frozen["digest"]})
    with pytest.raises(FileExistsError):
        ev.reduce(root, tmp_path / "nonexistent", tmp_path / "result", True)


def test_calibration_foreign_changed_and_scorer_bindings(experiment, tmp_path):
    root, frozen, spec = experiment
    qualify(root, tmp_path)
    assert ev.calibration_valid(root, frozen, spec, "blind-human")
    assert not ev.calibration_valid(root, frozen, spec, "another-human")
    receipt = root / "calibration-receipt.json"
    value = ev.load(receipt)
    value["score_digest"] = "foreign"
    rewrite(receipt, value)
    assert not ev.calibration_valid(root, frozen, spec, "blind-human")
    foreign_root = tmp_path / "foreign"
    foreign = ev.prepare(PILOT, foreign_root)
    ev.write_new(foreign_root / "calibration-receipt.json", value)
    assert not ev.calibration_valid(foreign_root, foreign, spec, "blind-human")


def test_installed_entrypoint_from_outside_repo(tmp_path):
    from importlib.metadata import distribution
    entry = next(e for e in distribution("phase-loop-runtime").entry_points
                 if e.name == "phase-loop-skill-eval")
    assert entry.value == "phase_loop_runtime.skill_eval:console_main"
    executable = Path(sys.executable).parent / entry.name
    # The installed editable package must resolve without caller PYTHONPATH or repo cwd.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for args in (["--help"], ["validate", "--spec", str(PILOT.resolve())]):
        result = subprocess.run([str(executable), *args], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr


def test_prepare_and_reduce_never_launch_or_touch_skills(experiment, tmp_path, monkeypatch):
    from phase_loop_runtime import launcher, panel_invoker
    monkeypatch.setattr(launcher, "launch", lambda *a, **k: pytest.fail("provider invoked"))
    monkeypatch.setattr(panel_invoker, "launch_owned", lambda *a, **k: pytest.fail("provider invoked"))
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    sentinel = skill_root / "reflection.md"
    sentinel.write_text("synthetic protected reflection; must remain unchanged")
    monkeypatch.setenv("PHASE_LOOP_SKILL_BUNDLE", str(skill_root))
    repo = PILOT.parents[4]
    canonical_before = {str(p): ev.digest(p.read_bytes()) for p in (repo / "skills-src").rglob("*")
                        if p.is_file()}
    root, frozen, spec = experiment
    qualify(root, tmp_path)
    _, _, path = scored_packet(root, tmp_path / "packet")
    result = ev.reduce(root, path, tmp_path / "result")
    assert all(c["status"] == "inconclusive" for c in result["comparisons"].values())
    assert all(not t["valid"] for t in result["trials"].values())
    assert sentinel.read_text() == "synthetic protected reflection; must remain unchanged"
    assert list(skill_root.iterdir()) == [sentinel]
    assert canonical_before == {str(p): ev.digest(p.read_bytes()) for p in (repo / "skills-src").rglob("*")
                                if p.is_file()}


def test_normal_scores_seal_before_reveal(experiment, tmp_path):
    root, frozen, spec = experiment
    seal(root, frozen, spec, frozen["schedule"][0])
    _, scores, path = scored_packet(root, tmp_path / "packet")
    ev.reduce(root, path, tmp_path / "result")
    scores["scores"][0]["items"]["r1"]["pass"] = False
    rewrite(path, scores)
    with pytest.raises(ValueError, match="already sealed"):
        ev.reduce(root, path, tmp_path / "revised-result")


def test_calibration_packet_cannot_drop_wrong_examples(experiment, tmp_path):
    root, frozen, spec = experiment
    ev.packet(root, tmp_path / "gold", True)
    path = root / "calibration-packet.json"
    value = ev.load(path)
    value["outputs"] = value["outputs"][:1]
    value["packet_digest"] = ev.digest({k: v for k, v in value.items() if k != "packet_digest"})
    rewrite(path, value)
    with pytest.raises(ValueError, match="frozen pack"):
        ev.checked_packet(root, frozen, spec, True)


def test_resealed_packet_cannot_add_foreign_output(experiment, tmp_path):
    root, frozen, spec = experiment
    seal(root, frozen, spec, frozen["schedule"][0])
    packet, scores, path = scored_packet(root, tmp_path / "packet")
    packet["outputs"].append({**packet["outputs"][0], "id": "foreign-output"})
    packet["packet_digest"] = ev.digest({k: v for k, v in packet.items() if k != "packet_digest"})
    rewrite(root / "packet.json", packet)
    scores["packet_digest"] = packet["packet_digest"]
    scores["scores"].append({**scores["scores"][0], "id": "foreign-output"})
    rewrite(path, scores)
    with pytest.raises(ValueError, match="unknown or no-longer-scoreable"):
        ev.reduce(root, path, tmp_path / "result")


@pytest.mark.parametrize("calibration", [False, True])
@pytest.mark.parametrize("field", ["prompt", "facts", "rubric"])
@pytest.mark.parametrize("marker_kind", ["model", "escaped_root"])
def test_packet_refuses_identity_in_natural_inputs(tmp_path, calibration, field, marker_kind):
    root = tmp_path / 'operator-"slash\\café' / "experiment"
    value = ev.load(PILOT)
    marker = value["model"] if marker_kind == "model" else str(root.resolve())
    case = value["comparisons"][0]["cases"][0]
    if field == "prompt":
        case["prompt"] += " " + marker
    elif field == "facts":
        case["files"]["notes.txt"] += marker
    else:
        case["rubric"]["r1"] += " " + marker
    spec_path = tmp_path / "spec.json"
    rewrite(spec_path, value)
    frozen = ev.prepare(spec_path, root)
    spec = ev.Spec.model_validate(frozen["spec"])
    trial = next(t for t in frozen["schedule"] if t["case"] == case["id"])
    seal(root, frozen, spec, trial)
    with pytest.raises(ValueError, match="identity marker"):
        ev.packet(root, tmp_path / "packet", calibration)
    assert not (root / ("calibration-packet.json" if calibration else "packet.json")).exists()


@pytest.mark.parametrize("marker_kind", ["model", "escaped_root"])
def test_unblinded_outputs_stay_private_and_all_invalid_trials_reported(tmp_path, marker_kind):
    root = tmp_path / 'operator-"slash\\café' / "experiment"
    frozen = ev.prepare(PILOT, root)
    spec = ev.Spec.model_validate(frozen["spec"])
    qualify(root, tmp_path)
    marker = spec.model if marker_kind == "model" else str(root.resolve())
    invalid = set()
    for trial in frozen["schedule"]:
        leak = trial["repetition"] == 0
        if leak:
            invalid.add(trial["id"])
        seal(root, frozen, spec, trial, text=marker if leak else "producer consumer control plan")
    packet, _, scores = scored_packet(root, tmp_path / "packet")
    assert len(packet["outputs"]) == 48 - len(invalid)
    result = ev.reduce(root, scores, tmp_path / "result")
    assert set(result["trials"]) == {t["id"] for t in frozen["schedule"]}
    assert {k for k, v in result["trials"].items() if not v["valid"]} == invalid
    assert all(result["trials"][k]["reason"] == "unblinded output" for k in invalid)
    assert {c["status"] for c in result["comparisons"].values()} == {"inconclusive"}
    for trial in frozen["schedule"]:
        if trial["id"] in invalid:
            assert ev.load(root / "trials" / trial["id"] / "terminal.json")["output"] == marker


def test_calibration_refuses_identity_in_gold_output(tmp_path):
    value = ev.load(PILOT)
    value["gold"][0]["text"] += " " + value["model"]
    path = tmp_path / "spec.json"
    rewrite(path, value)
    root = tmp_path / "experiment"
    ev.prepare(path, root)
    with pytest.raises(ValueError, match="identity marker"):
        ev.packet(root, tmp_path / "gold", True)


@pytest.mark.parametrize("calibration", [False, True])
@pytest.mark.parametrize("shape", ["array", "scores_object", "row_array", "items_array", "item_array", "json"])
def test_cli_refuses_malformed_scores_without_traceback(experiment, tmp_path, calibration, shape):
    root, frozen, spec = experiment
    seal(root, frozen, spec, frozen["schedule"][0])
    _, scores, path = scored_packet(root, tmp_path / "packet", calibration=calibration)
    if shape == "array":
        scores = []
    elif shape == "scores_object":
        scores["scores"] = {}
    elif shape == "row_array":
        scores["scores"][0] = ["id", "items"]
    elif shape == "items_array":
        scores["scores"][0]["items"] = list(scores["scores"][0]["items"])
    elif shape == "item_array":
        scores["scores"][0]["items"]["r1"] = ["pass", "quote"]
    rewrite(path, scores)
    if shape == "json":
        path.write_text("{malformed")
    raw = path.read_bytes()
    command = [str(Path(sys.executable).parent / "phase-loop-skill-eval"), "reduce",
               "--experiment", str(root), "--scores", str(path), "--out", str(tmp_path / "result")]
    if calibration:
        command.append("--calibration")
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "skill-eval refused:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "result").exists()
    if calibration:
        receipt = ev.load(root / "calibration-receipt.json")
        assert receipt["passed"] is False
        assert receipt["score_digest"] == ev.digest(raw)
        assert receipt["score_bytes"] == raw.decode()
        assert receipt["scorer_id"] == (scores.get("scorer_id") if isinstance(scores, dict) and shape != "json" else None)
        assert not ev.calibration_valid(root, frozen, spec, "blind-human")
        retry = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert retry.returncode == 2 and "skill-eval refused:" in retry.stderr
        assert ev.load(root / "calibration-receipt.json") == receipt
    else:
        assert not (root / "scores-sealed.json").exists()


def test_malformed_nested_access_is_invalid_evidence(experiment):
    root, frozen, spec = experiment
    trial = frozen["schedule"][0]
    seal(root, frozen, spec, trial)
    directory = root / "trials" / trial["id"]
    access = ev.load(directory / "access.json")
    access["events"][ev.GUIDE] = ["open", "access"]
    rewrite(directory / "access.json", access)
    terminal = ev.load(directory / "terminal.json")
    terminal["access_digest"] = ev.digest(access)
    rewrite(directory / "terminal.json", terminal)
    assert not ev.evidence(root, frozen, spec, trial)["valid"]


@pytest.mark.parametrize("malformed", [None, "packet", 1, []])
def test_non_object_packet_refused(experiment, tmp_path, malformed):
    root, frozen, spec = experiment
    rewrite(root / "packet.json", malformed)
    with pytest.raises(ValueError):
        ev.checked_packet(root, frozen, spec, False)


def test_calibration_missing_file_consumes_attempt(experiment, tmp_path):
    root, frozen, spec = experiment
    ev.packet(root, tmp_path / "gold", True)
    with pytest.raises(ValueError, match="regular JSON file"):
        ev.reduce(root, tmp_path / "missing", tmp_path / "result", True)
    assert (root / "calibration-started.json").exists()
    assert not (root / "calibration-receipt.json").exists()
    with pytest.raises(FileExistsError):
        ev.reduce(root, tmp_path / "missing", tmp_path / "retry", True)
    assert not ev.calibration_valid(root, frozen, spec, "blind-human")


@pytest.mark.parametrize("malformed", [[], {"score_bytes": []}])
def test_malformed_calibration_receipt_cannot_qualify(experiment, malformed):
    root, frozen, spec = experiment
    ev.write_new(root / "calibration-started.json", {"experiment": frozen["digest"]})
    rewrite(root / "calibration-receipt.json", malformed)
    assert not ev.calibration_valid(root, frozen, spec, "blind-human")


def test_malformed_scorer_identity_stays_null_in_failed_receipt(experiment, tmp_path):
    root, frozen, spec = experiment
    _, scores, path = scored_packet(root, tmp_path / "gold", calibration=True)
    scores["scorer_id"] = ["invented-scorer"]
    rewrite(path, scores)
    with pytest.raises(ValueError, match="invalid calibration scores"):
        ev.reduce(root, path, tmp_path / "result", True)
    receipt = ev.load(root / "calibration-receipt.json")
    assert receipt["scorer_id"] is None and receipt["passed"] is False
    assert not ev.calibration_valid(root, frozen, spec, "invented-scorer")


def test_non_string_terminal_output_is_invalid_evidence(experiment):
    root, frozen, spec = experiment
    trial = frozen["schedule"][0]
    seal(root, frozen, spec, trial)
    path = root / "trials" / trial["id"] / "terminal.json"
    terminal = ev.load(path)
    terminal["output"] = []
    rewrite(path, terminal)
    assert not ev.evidence(root, frozen, spec, trial)["valid"]
