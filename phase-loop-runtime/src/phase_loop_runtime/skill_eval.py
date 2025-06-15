"""Opt-in, frozen diagnostic planning comparisons. No automatic skill adoption."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import random
import sys
import tempfile
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ModelSelection


ANCHOR = "3. Inspect likely implementation and test files."
BASELINE_SHA256 = "91cd1492fb85eb264327098f6c18604bb26d4301cef73275942fcb415925feab"
CANDIDATES = {
    "layer": ANCHOR + "\nFor an installed or deployed defect, identify the failing layer and compare its identity with current source and any existing repair or release owner. Scope the plan to the unresolved layer; record separately owned dependencies and qualification still required.",
    "oracle": "Inspect implementation and test files, tracing each proposed acceptance fixture through its real producer and observable consumer. Name a supported alternate path when the change affects one, and choose controls that fail on the intended behavior rather than setup.",
}
GUIDE = ".guidance/plan.md"
ROUTE = "For planning tasks read .guidance/plan.md. Deliver only the final-response plan.\n"
ENVELOPE = (
    "This is a plain snapshot without .git. Read AGENTS.md and the planning guide. "
    "Use fixture-only facts and relative-path evidence. Deliver only a final-response plan. "
    "Do not write artifacts, manifests, handoffs or reflections. Do not quote the guide "
    "or disclose provider, model, arm or operator paths.\n\n"
)
DECISION = {"target_wins": 3, "target_losses": 0, "control_losses": 0}


def digest(value) -> str:
    raw = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def load(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected a regular JSON file")
    return parse_json(path.read_bytes())


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def write_new(path: Path, value):
    """Publish a complete immutable record without overwriting a previous claim."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".record-")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink()


@contextmanager
def experiment_lock(root: Path):
    if sys.platform != "linux":
        raise ValueError("Linux required")
    import fcntl
    with (root / ".lock").open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("experiment already locked") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def safe_name(name: str):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or str(path) != name or
            any(part in {"..", ".", ".git", ".guidance"} for part in path.parts) or
            "\\" in name or "\x00" in name or name == "AGENTS.md"):
        raise ValueError("unsafe fixture name")
    return name


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Edit(Strict):
    old: str
    new: str


class Case(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]+$")
    kind: str
    prompt: str = Field(min_length=1)
    files: dict[str, str]
    required: list[str]
    rubric: dict[str, str]

    @model_validator(mode="after")
    def validate_case(self):
        if self.kind not in {"target", "negative_control"} or not self.files or not self.rubric:
            raise ValueError("case requires kind, files and binary rubric")
        for name in self.files:
            safe_name(name)
        names = sorted(self.files)
        if any(b.startswith(a + "/") for a in names for b in names if a != b):
            raise ValueError("fixture file/directory collision")
        if (not self.required or len(set(self.required)) != len(self.required) or
                not set(self.required) <= set(self.files)):
            raise ValueError("invalid required read paths")
        if any(not key or not text.strip() for key, text in self.rubric.items()):
            raise ValueError("empty rubric")
        return self


class Comparison(Strict):
    id: str
    edit: Edit
    cases: list[Case]


class Executable(Strict):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    version: str = Field(min_length=1)
    diagnostic_allowlist: list[str]


class Gold(Strict):
    case_id: str
    text: str = Field(min_length=1)
    annotations: dict[str, bool]
    citations: dict[str, str]


class Spec(Strict):
    version: int
    model: str = Field(min_length=1)
    effort: str
    profile: str
    executable: Executable
    baseline_commit: str
    baseline: str
    comparisons: list[Comparison]
    repetitions: int
    allocation_seed: int
    gold: list[Gold]
    decision: dict[str, int]

    @model_validator(mode="after")
    def validate_spec(self):
        if (self.version != 1 or self.profile != "plan" or self.repetitions != 3 or
                self.decision != DECISION or
                self.baseline_commit != "b9892d298aa23297e3f37eea5e2b4995c67ec60e"):
            raise ValueError("unsupported pilot protocol")
        if self.effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("explicit Codex effort required")
        ModelSelection(profile=self.profile, model=self.model, effort=self.effort)
        if not Path(self.executable.path).is_absolute():
            raise ValueError("absolute pinned executable required")
        # Diagnostics are exact lines, version-bound. The pilot preregisters none.
        if self.executable.diagnostic_allowlist:
            raise ValueError("this protocol allows no non-JSON diagnostics")
        if self.baseline.count(ANCHOR) != 1 or digest(self.baseline.encode()) != BASELINE_SHA256:
            raise ValueError("pinned baseline bytes and unique anchor required")
        if sorted(c.id for c in self.comparisons) != ["layer", "oracle"]:
            raise ValueError("two independent comparisons required")
        ids = []
        for comparison in self.comparisons:
            if comparison.edit.old != ANCHOR or comparison.edit.new != CANDIDATES[comparison.id]:
                raise ValueError("candidate must match reviewed edit")
            if (len(comparison.cases) != 4 or
                    sorted(c.kind for c in comparison.cases) !=
                    ["negative_control", "target", "target", "target"]):
                raise ValueError("three target cases and one negative control required")
            ids.extend(c.id for c in comparison.cases)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case IDs")
        cases = {c.id: c for group in self.comparisons for c in group.cases}
        for case_id, case in cases.items():
            gold = [g for g in self.gold if g.case_id == case_id]
            if len(gold) != 2 or {all(g.annotations.values()) for g in gold} != {True, False}:
                raise ValueError("independent good and wrong gold required for every case")
            for example in gold:
                if (set(example.annotations) != set(case.rubric) or
                        set(example.citations) != set(case.rubric) or
                        any(not quote or quote not in example.text for quote in example.citations.values())):
                    raise ValueError("invalid gold annotations or citations")
        if len(self.gold) != 16 or any(g.case_id not in cases for g in self.gold):
            raise ValueError("unknown gold case")
        return self


def runtime_identity():
    from importlib.metadata import version
    return {"version": version("phase-loop-runtime"), "python": sys.version,
            "modules": {name: digest(Path(__file__).with_name(name).read_bytes())
                        for name in ("skill_eval.py", "skill_eval_runner.py", "skill_eval_access.py",
                                     "launcher.py", "panel_invoker.py", "sandbox_egress.py",
                                     "review_stage.py", "sandbox_policy.py")}}


def protocol_config(spec: Spec):
    from .skill_eval_runner import command_for
    return {"locale": "C", "argv": command_for(Path("/SUBJECT"), spec, "TASK"),
            "diagnostic_allowlist": spec.executable.diagnostic_allowlist,
            "guide_path": GUIDE, "route": ROUTE, "envelope": ENVELOPE}


def prepare(spec_path: Path, root: Path):
    spec = Spec.model_validate(load(spec_path))
    frozen = {"spec": spec.model_dump(), "spec_bytes_digest": digest(spec_path.read_bytes()),
              "input_hashes": {"baseline": digest(spec.baseline.encode()),
                               "gold": digest([g.model_dump() for g in spec.gold]),
                               "cases": digest([c.model_dump() for g in spec.comparisons for c in g.cases])},
              "runtime": runtime_identity(),
              "config": protocol_config(spec), "schedule": [], "arms": {}}
    rng = random.Random(spec.allocation_seed)
    for group in spec.comparisons:
        arms = {uuid.uuid4().hex: spec.baseline,
                uuid.uuid4().hex: spec.baseline.replace(group.edit.old, group.edit.new, 1)}
        baseline, treatment = arms
        frozen["arms"][group.id] = {"baseline": baseline, "treatment": treatment, "bytes": arms}
        orders = [False] * 6 + [True] * 6
        rng.shuffle(orders)
        pairs = [(case, rep) for case in group.cases for rep in range(3)]
        rng.shuffle(pairs)
        for (case, rep), reverse in zip(pairs, orders):
            for arm in ([treatment, baseline] if reverse else [baseline, treatment]):
                frozen["schedule"].append({"id": uuid.uuid4().hex, "output_id": uuid.uuid4().hex,
                                           "comparison": group.id, "case": case.id,
                                           "repetition": rep, "arm": arm})
    frozen["digest"] = digest(frozen)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_new(root / "frozen.json", frozen)
    return frozen


def open_experiment(root: Path):
    frozen = load(root / "frozen.json")
    original = frozen.copy()
    stored = original.pop("digest")
    if digest(original) != stored:
        raise ValueError("frozen inputs changed")
    spec = Spec.model_validate(frozen["spec"])
    if frozen["runtime"] != runtime_identity() or frozen["config"] != protocol_config(spec):
        raise ValueError("runtime or command configuration changed; prepare a new experiment")
    schedule = frozen["schedule"]
    if len(schedule) != 48 or len({t["id"] for t in schedule}) != 48 or len({t["output_id"] for t in schedule}) != 48:
        raise ValueError("inconsistent schedule")
    for group in spec.comparisons:
        arms = frozen["arms"][group.id]
        expected = {arms["baseline"]: spec.baseline,
                    arms["treatment"]: spec.baseline.replace(group.edit.old, group.edit.new, 1)}
        if len(expected) != 2 or arms["bytes"] != expected:
            raise ValueError("inconsistent arm bytes")
        first = []
        for case in group.cases:
            for rep in range(3):
                pair = [t for t in schedule if t["comparison"] == group.id and
                        t["case"] == case.id and t["repetition"] == rep]
                if len(pair) != 2 or {t["arm"] for t in pair} != set(expected):
                    raise ValueError("inconsistent pair")
                first.append(pair[0]["arm"])
        if first.count(arms["baseline"]) != 6:
            raise ValueError("unbalanced schedule")
    return frozen, spec


def case_for(spec, trial):
    return next(case for group in spec.comparisons if group.id == trial["comparison"]
                for case in group.cases if case.id == trial["case"])


def files_for(frozen, spec, trial):
    case = case_for(spec, trial)
    return {**case.files, "AGENTS.md": ROUTE,
            GUIDE: frozen["arms"][trial["comparison"]]["bytes"][trial["arm"]]}


def binding(frozen, spec, trial):
    files = files_for(frozen, spec, trial)
    return {"experiment": frozen["digest"], "trial": trial["id"],
            "files_digest": digest(files), "guide_digest": digest(files[GUIDE].encode())}


def run(root: Path):
    from .skill_eval_runner import run_trial
    os.environ["LC_ALL"] = "C"
    with experiment_lock(root):
        frozen, spec = open_experiment(root)
        for trial in frozen["schedule"]:
            started = root / "trials" / trial["id"] / "started.json"
            if started.exists():
                continue
            bound = binding(frozen, spec, trial)
            write_new(started, bound)
            run_trial(root, frozen, spec, trial)


def evidence(root, frozen, spec, trial):
    directory = root / "trials" / trial["id"]
    expected = binding(frozen, spec, trial)
    try:
        if load(directory / "started.json") != expected:
            raise ValueError("started binding mismatch")
        terminal = load(directory / "terminal.json")
        if terminal["binding"] != expected:
            raise ValueError("terminal binding mismatch")
        output = terminal["output"]
        if not isinstance(output, str):
            raise ValueError("malformed final output")
        output_digest = digest(output.encode())
        for name in ("launch", "access"):
            receipt = load(directory / (name + ".json"))
            if receipt["binding"] != {**expected, "output_digest": output_digest}:
                raise ValueError("receipt join mismatch")
            if digest(receipt) != terminal[name + "_digest"]:
                raise ValueError("receipt changed")
        launch = load(directory / "launch.json")
        access = load(directory / "access.json")
        if (terminal["status"] != "completed" or terminal["output_digest"] != output_digest or
                launch["returncode"] != 0 or launch["probe"] != "passed" or
                launch["stream_valid"] is not True or not output.strip() or access["errors"]):
            raise ValueError("unsuccessful launch or observation")
        paths = files_for(frozen, spec, trial)
        if not isinstance(access["events"], dict) or set(access["events"]) != set(paths) or any(
                not isinstance(events, dict) or set(events) != {"open", "access"}
                for events in access["events"].values()) or any(
                type(flag) is not bool for events in access["events"].values()
                for flag in events.values()):
            raise ValueError("incomplete access map")
        if access["events"][GUIDE]["access"] is not True:
            raise ValueError("unexposed: guide access missing")
        transcript = (directory / "transcript.txt").read_bytes()
        if digest(transcript) != launch["transcript_digest"]:
            raise ValueError("transcript changed")
        return {"valid": True, "output": output, "access": access["events"],
                "usage": launch["usage"], "elapsed_seconds": launch["elapsed_seconds"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"valid": False, "reason": str(exc) if isinstance(exc, ValueError)
                else "missing or malformed evidence"}


def rubric_digest(spec):
    return digest({c.id: c.rubric for g in spec.comparisons for c in g.cases})


def identity_markers(root, frozen, spec):
    from .sandbox_policy import staging_root
    return [spec.model, spec.executable.path, str(root.resolve()), str(staging_root().resolve()),
            *[arm for group in frozen["arms"].values() for arm in group["bytes"]]]


def unblinded(value, markers):
    if isinstance(value, str):
        return any(marker in value for marker in markers)
    if isinstance(value, dict):
        return any(unblinded(k, markers) or unblinded(v, markers) for k, v in value.items())
    if isinstance(value, list):
        return any(unblinded(item, markers) for item in value)
    return False


def check_blind_inputs(root, frozen, spec, calibration):
    markers = identity_markers(root, frozen, spec)
    for group in spec.comparisons:
        for case in group.cases:
            if unblinded([case.prompt, case.files, case.rubric], markers):
                raise ValueError("packet input contains preregistered identity marker")
    if calibration and unblinded([g.text for g in spec.gold], markers):
        raise ValueError("gold packet contains preregistered identity marker")
    return markers


def packet(root: Path, out: Path, calibration=False):
    with experiment_lock(root):
        frozen, spec = open_experiment(root)
        markers = check_blind_inputs(root, frozen, spec, calibration)
        name = "calibration-packet.json" if calibration else "packet.json"
        stored = root / name
        if stored.exists():
            result = checked_packet(root, frozen, spec, calibration)
        else:
            rows = []
            if calibration:
                cases = {c.id: c for g in spec.comparisons for c in g.cases}
                for index, gold in enumerate(spec.gold):
                    case = cases[gold.case_id]
                    rows.append({"id": uuid.uuid4().hex, "task": case.prompt, "facts": case.files,
                                 "plan": gold.text, "rubric": case.rubric, "access": {}})
                random.SystemRandom().shuffle(rows)
            else:
                for trial in frozen["schedule"]:
                    item = evidence(root, frozen, spec, trial)
                    if not item["valid"]:
                        continue
                    case = case_for(spec, trial)
                    row = {"id": trial["output_id"], "task": case.prompt, "facts": case.files,
                           "plan": item["output"], "rubric": case.rubric,
                           "access": {p: item["access"][p] for p in case.files}}
                    if unblinded(item["output"], markers):
                        continue
                    rows.append(row)
                random.SystemRandom().shuffle(rows)
            result = {"version": 1, "experiment": frozen["digest"], "rubric_digest": rubric_digest(spec),
                      "calibration": calibration, "outputs": rows}
            result["packet_digest"] = digest(result)
            # Refuse rather than redact any identity-bearing natural task or fixture.
            if unblinded(rows, markers):
                raise ValueError("packet contains preregistered identity marker")
            write_new(stored, result)
        out.mkdir(mode=0o700, parents=True, exist_ok=False)
        write_new(out / "packet.json", result)
        form = {"scorer_id": "", "no_prior_gold_exposure": False,
                "experiment": result["experiment"], "packet_digest": result["packet_digest"],
                "rubric_digest": result["rubric_digest"], "scores": [
                    {"id": row["id"], "items": {key: {"pass": None, "quote": ""}
                                               for key in row["rubric"]}}
                    for row in result["outputs"]]}
        write_new(out / "scores.json", form)
        return result


def check_scores(scores, packet):
    if not isinstance(scores, dict) or set(scores) != {"scorer_id", "no_prior_gold_exposure", "experiment",
                      "packet_digest", "rubric_digest", "scores"}:
        raise ValueError("unknown score fields")
    if (not isinstance(scores["scorer_id"], str) or not scores["scorer_id"].strip() or
            type(scores["no_prior_gold_exposure"]) is not bool or
            any(scores[key] != packet[key] for key in ("experiment", "packet_digest", "rubric_digest"))):
        raise ValueError("foreign score packet or missing scorer")
    if not isinstance(scores["scores"], list):
        raise ValueError("scores must be an array")
    rows = {row["id"]: row for row in packet["outputs"]}
    votes = {}
    for score in scores["scores"]:
        if (not isinstance(score, dict) or set(score) != {"id", "items"} or
                not isinstance(score["id"], str) or score["id"] not in rows or score["id"] in votes):
            raise ValueError("unknown or duplicate score ID")
        row = rows[score["id"]]
        if not isinstance(score["items"], dict) or set(score["items"]) != set(row["rubric"]):
            raise ValueError("all rubric items required")
        for item in score["items"].values():
            if (not isinstance(item, dict) or set(item) != {"pass", "quote"} or type(item["pass"]) is not bool or
                    not isinstance(item["quote"], str) or not item["quote"] or
                    item["quote"] not in row["plan"]):
                raise ValueError("exact Boolean score and output citation required")
        votes[score["id"]] = {key: item["pass"] for key, item in score["items"].items()}
    if set(votes) != set(rows):
        raise ValueError("missing scoreable IDs")
    return votes


def checked_packet(root, frozen, spec, calibration):
    markers = check_blind_inputs(root, frozen, spec, calibration)
    stored = load(root / ("calibration-packet.json" if calibration else "packet.json"))
    if (not isinstance(stored, dict) or set(stored) != {
            "version", "experiment", "rubric_digest", "calibration", "outputs", "packet_digest"} or
            type(stored["version"]) is not int or stored["version"] != 1 or
            type(stored["calibration"]) is not bool or not isinstance(stored["outputs"], list)):
        raise ValueError("invalid packet fields")
    payload = stored.copy()
    claimed = payload.pop("packet_digest")
    if (digest(payload) != claimed or stored["experiment"] != frozen["digest"] or
            stored["rubric_digest"] != rubric_digest(spec) or stored["calibration"] != calibration):
        raise ValueError("packet changed or foreign")
    rows = stored["outputs"]
    if any(not isinstance(row, dict) or
           set(row) != {"id", "task", "facts", "plan", "rubric", "access"} or
           any(not isinstance(row[key], str) for key in ("id", "task", "plan")) or
           any(not isinstance(row[key], dict) for key in ("facts", "rubric", "access"))
           for row in rows) or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("invalid packet fields or duplicate IDs")
    if unblinded(rows, markers):
        raise ValueError("packet contains preregistered identity marker")
    if calibration:
        cases = {c.id: c for g in spec.comparisons for c in g.cases}
        expected = [{"task": cases[g.case_id].prompt, "facts": cases[g.case_id].files,
                     "plan": g.text, "rubric": cases[g.case_id].rubric, "access": {}} for g in spec.gold]
        actual = [{k: v for k, v in row.items() if k != "id"} for row in rows]
        if sorted(map(digest, actual)) != sorted(map(digest, expected)):
            raise ValueError("gold packet differs from frozen pack")
    return stored


def calibrate(root, frozen, spec, scores_path):
    # Claim before parsing/evaluating; failed and interrupted attempts consume the slot.
    write_new(root / "calibration-started.json", {"experiment": frozen["digest"]})
    packet_data = checked_packet(root, frozen, spec, True)
    if scores_path.is_symlink() or not scores_path.is_file():
        raise ValueError("expected a regular JSON file")
    raw = scores_path.read_bytes()
    score_text = raw.decode()
    scores = None
    verdict = False
    error = None
    try:
        scores = parse_json(raw)
        votes = check_scores(scores, packet_data)
        gold = {g.text: g for g in spec.gold}
        verdict = scores["no_prior_gold_exposure"] is True and all(
            votes[row["id"]] == gold[row["plan"]].annotations for row in packet_data["outputs"])
    except (ValueError, KeyError, TypeError) as exc:
        error = exc
    scorer = scores.get("scorer_id") if isinstance(scores, dict) else None
    if not isinstance(scorer, str) or not scorer.strip():
        scorer = None
    receipt = {"experiment": frozen["digest"], "packet_digest": packet_data["packet_digest"],
               "rubric_digest": rubric_digest(spec), "gold_digest": digest(frozen["spec"]["gold"]),
               "scorer_id": scorer, "scores": scores,
               "score_bytes": score_text, "score_digest": digest(raw), "passed": verdict}
    write_new(root / "calibration-receipt.json", receipt)
    if error is not None:
        raise ValueError(f"invalid calibration scores: {error}") from error
    return {"calibration_passed": verdict}


def calibration_valid(root, frozen, spec, scorer):
    try:
        if load(root / "calibration-started.json") != {"experiment": frozen["digest"]}:
            return False
        receipt = load(root / "calibration-receipt.json")
        if (not isinstance(receipt, dict) or
                not isinstance(receipt.get("score_bytes"), str)):
            return False
        packet_data = checked_packet(root, frozen, spec, True)
        votes = check_scores(receipt["scores"], packet_data)
        gold = {g.text: g for g in spec.gold}
        return (receipt["passed"] is True and receipt["scorer_id"] == scorer and
                receipt["scorer_id"] == receipt["scores"]["scorer_id"] and
                receipt["scores"]["no_prior_gold_exposure"] is True and
                receipt["experiment"] == frozen["digest"] and
                receipt["packet_digest"] == packet_data["packet_digest"] and
                receipt["rubric_digest"] == rubric_digest(spec) and
                receipt["gold_digest"] == digest(frozen["spec"]["gold"]) and
                digest(receipt["score_bytes"].encode()) == receipt["score_digest"] and
                json.loads(receipt["score_bytes"]) == receipt["scores"] and
                all(votes[row["id"]] == gold[row["plan"]].annotations for row in packet_data["outputs"]))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def reduce(root: Path, scores_path: Path, out: Path, calibration=False):
    with experiment_lock(root):
        frozen, spec = open_experiment(root)
        if calibration:
            result = calibrate(root, frozen, spec, scores_path)
        else:
            packet_data = checked_packet(root, frozen, spec, False)
            scores = load(scores_path)
            votes = check_scores(scores, packet_data)
            sealed = {"scores": scores, "score_bytes_digest": digest(scores_path.read_bytes())}
            seal_path = root / "scores-sealed.json"
            if seal_path.exists():
                if load(seal_path) != sealed:
                    raise ValueError("scores already sealed; changed judgments refused")
            else:
                write_new(seal_path, sealed)
            markers = identity_markers(root, frozen, spec)
            rows = {row["id"]: row for row in packet_data["outputs"]}
            trials = {}
            scoreable_ids = set()
            for trial in frozen["schedule"]:
                item = evidence(root, frozen, spec, trial)
                if item["valid"]:
                    case = case_for(spec, trial)
                    row = rows.get(trial["output_id"])
                    if unblinded(item["output"], markers):
                        item = {"valid": False, "reason": "unblinded output"}
                    elif row is None or row != {
                            "id": trial["output_id"], "task": case.prompt, "facts": case.files,
                            "plan": item["output"], "rubric": case.rubric,
                            "access": {p: item["access"][p] for p in case.files}}:
                        raise ValueError("packet does not match current scoreable evidence")
                    else:
                        scoreable_ids.add(trial["output_id"])
                        item["pass"] = (all(votes[trial["output_id"]].values()) and
                                        all(item["access"][p]["access"] for p in case.required))
                        del item["output"]
                trials[trial["id"]] = item
            if set(rows) != scoreable_ids:
                raise ValueError("packet contains unknown or no-longer-scoreable output IDs")
            calibrated = calibration_valid(root, frozen, spec, scores["scorer_id"])
            comparisons = {}
            for group in spec.comparisons:
                counts = {kind: {"wins": 0, "losses": 0, "ties": 0}
                          for kind in ("target", "negative_control")}
                invalid = False
                sensitive = True
                arms = frozen["arms"][group.id]
                for case in group.cases:
                    for rep in range(3):
                        pair = {t["arm"]: trials[t["id"]] for t in frozen["schedule"] if
                                t["comparison"] == group.id and t["case"] == case.id and t["repetition"] == rep}
                        if not all(t["valid"] for t in pair.values()):
                            invalid = True
                            continue
                        baseline, treatment = pair[arms["baseline"]]["pass"], pair[arms["treatment"]]["pass"]
                        if case.kind == "negative_control" and not baseline:
                            sensitive = False
                        outcome = "ties" if baseline == treatment else ("wins" if treatment else "losses")
                        counts[case.kind][outcome] += 1
                status = "no demonstrated improvement"
                if invalid or not sensitive or not calibrated:
                    status = "inconclusive"
                elif (counts["target"]["wins"] >= 3 and counts["target"]["losses"] == 0 and
                      counts["negative_control"]["losses"] == 0):
                    status = "promising"
                comparisons[group.id] = {"status": status, "pairs": counts, "control_sensitive": sensitive,
                                         "invalid_trials": invalid}
            result = {"experiment": frozen["digest"], "scores_digest": digest(scores_path.read_bytes()),
                      "calibrated": calibrated, "comparisons": comparisons, "trials": trials,
                      "operational_qualification": "pending explicitly started live pilot",
                      "interpretation": "Diagnostic pilot only; no significance, independent-incident, adoption or editor-gating claim."}
        out.mkdir(parents=True, mode=0o700, exist_ok=False)
        write_new(out / "result.json", result)
        (out / "result.md").write_text("# Skill evaluation\n\n" + (
            "Calibration passed.\n" if result.get("calibration_passed") else
            ("Calibration failed.\n" if calibration else "\n".join(
                f"- {name}: {item['status']}" for name, item in result["comparisons"].items()) +
             "\n\nLive operational qualification and editor gating remain pending.\n")))
        return result


def console_main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "prepare", "run", "packet", "reduce"):
        child = sub.add_parser(command)
        if command in {"validate", "prepare"}:
            child.add_argument("--spec", type=Path, required=True)
        else:
            child.add_argument("--experiment", type=Path, required=True)
        if command in {"prepare", "packet", "reduce"}:
            child.add_argument("--out", type=Path, required=True)
        if command == "reduce":
            child.add_argument("--scores", type=Path, required=True)
        if command in {"packet", "reduce"}:
            child.add_argument("--calibration", action="store_true")
    args = parser.parse_args()
    os.environ["LC_ALL"] = "C"
    try:
        if args.command == "validate":
            Spec.model_validate(load(args.spec))
        elif args.command == "prepare":
            prepare(args.spec, args.out)
        elif args.command == "run":
            run(args.experiment)
        elif args.command == "packet":
            packet(args.experiment, args.out, args.calibration)
        else:
            reduce(args.experiment, args.scores, args.out, args.calibration)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        parser.exit(2, f"skill-eval refused: {exc}\n")
